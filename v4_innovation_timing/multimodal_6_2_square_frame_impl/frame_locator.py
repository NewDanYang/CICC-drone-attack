"""FM9G perception bridge for the square-crossing-frame (square_frame) category.

Mirrors the already-flight-validated balloon bridge (`runtime.PerceptionBridge` +
`presence.NativePresenceSweep`) and shares the same single model/tokenizer/processor
instance and `model_lock`, so it never loads a second copy of FM9G4B-V. The only new
surface is: a different prompt, a different publish target, and a one-shot localize
loop instead of a persistent track loop, because `TargetLocator` (official baseline,
unmodified) already does its own 10-sample temporal smoothing -- this module's job
is just to keep feeding it independent, model-only detections, exactly the way YOLO
used to.

Design note (see multimodal_6_0_square_frame_scope/REPORT.md and
multimodal_6_2_square_frame_impl/REPORT.md for the full reasoning):

  * Publishes to the EXISTING /objects topic using the EXISTING common_msgs/Objects
    schema `TargetLocator` already consumes (via `TargetDetectorBase`, which filters
    purely on `class_name == object_name and score >= confidence_threshold` -- no
    header/frame_id checks, unlike the balloon side's MultimodalTargetTracker). This
    requires ZERO C++ changes and ZERO new BT node types.
  * YOLO's own square_frame publish on /objects must be disabled for the duration of
    this bridge being active (drop "square_frame" from
    object_det/config/detection_params.yaml's `target_classes`), otherwise two
    independent publishers race on /objects and FM9G would not be the sole target
    identifier -- that is a deployment/config change, not something this module does
    itself; see the REPORT for the exact diff and why it needs Astra's real-flight
    validation rather than being applied here.
  * Self-gates off permanently the first time it observes a message on
    /multimodal/balloon_target (the balloon bridge's existing start/stop gate topic).
    By the time balloon tracking ever starts, square_frame identification (forward
    pass only, per the rule-scope note that reusing the live-computed frame_center on
    the reverse pass does not violate the no-preset-trajectory rule) is long done, so
    this is a correct, zero-new-signal way to stop burning GPU time on square_frame
    detection for the rest of the flight instead of adding a new ROS message.
"""
from datetime import datetime, timezone
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image as PILImage
import rospy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from common_msgs.msg import Objects, Obj
from .presence import NativePresenceSweep

PROMPT = "这张图片里有没有方形穿越框？只回答“是”或“否”。"
CLASS_NAME = "square_frame"
SOURCE_ID_FRONT = 1


def decode_bgr(msg):
    channels = {'rgb8': 3, 'bgr8': 3, 'rgba8': 4, 'bgra8': 4}.get(msg.encoding)
    if channels is None or msg.step < msg.width * channels or len(msg.data) != msg.height * msg.step:
        raise ValueError('Unsupported/malformed RGB image')
    rows = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
    array = rows[:, :msg.width * channels].reshape(msg.height, msg.width, channels)[:, :, :3]
    return (array[:, :, ::-1] if msg.encoding.startswith('rgb') else array).copy()


class FrameLocatorBridge:
    """One-shot-per-frame FM9G localizer for square_frame, feeding the unmodified
    TargetLocator BT node via the shared /objects topic. Never commands flight.

    Deliberately does NOT modify or reuse the balloon bridge's own
    `NativePresenceSweep` instance: that instance's `call()` gates every inference on
    an `active(epoch)` callback tied to the balloon session/epoch, which is false for
    the whole early-mission window this module runs in (before any balloon session
    exists) -- sharing it would make every square_frame call raise
    "presence inference became inactive". Instead this module builds its OWN
    `NativePresenceSweep` instance with its own epoch/active/audit, passing in the
    SAME `model`, `tokenizer`, `processor`, `model_lock` objects the balloon bridge
    was given. That keeps the hard constraint "只加载一份模型" (only one FM9G4B-V
    weight set loaded) intact -- only a second lightweight Python wrapper object is
    created, not a second copy of the model -- while giving this module its own,
    correctly-scoped activity gate. Calls to the GPU still serialize through the one
    shared `model_lock`, exactly like the balloon bridge's track/acquire calls do.
    """

    def __init__(self, model, tokenizer, processor, model_lock, audit_root=None):
        self.model_lock = model_lock
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.active = True  # starts active at construction time (early mission phase)
        self.frame = None
        self.frame_seq = 0
        self.header_seq = 0
        self.pending = False
        root = Path(audit_root or '/home/ubuntu/tcei_baseline_tools/results/multimodal_frame_v1')
        self.output = root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_') + uuid.uuid4().hex[:6])
        (self.output / 'images').mkdir(parents=True)
        self.log = (self.output / 'audit.jsonl').open('w', encoding='utf-8', buffering=1)
        # Own NativePresenceSweep instance, own epoch/active gate -- see class
        # docstring for why this can't be the balloon bridge's shared instance.
        # res/n_initial match the balloon side's acquire() settings exactly, since
        # square_frame localization uses the same tile-scan-then-sweep shape; n_track
        # and window_factor are irrelevant here (this module never calls .track()).
        self._epoch = 1
        self.presence = NativePresenceSweep(
            model, tokenizer, processor, model_lock, self.audit,
            active=lambda epoch: epoch == self._epoch and self.active and not self.stop_event.is_set(),
            res=224, n_initial=8)
        self.presence.warmup(text=PROMPT)
        self.objects_pub = rospy.Publisher('/objects', Objects, queue_size=1)
        self.debug_pub = rospy.Publisher('/multimodal/frame_debug_image', Image, queue_size=1)
        self.image_topic = '/rflysim/sensor1/img_rgb'
        self.subs = [
            rospy.Subscriber(self.image_topic, Image, self.on_image, queue_size=1, buff_size=4 * 1024 * 1024),
            rospy.Subscriber('/multimodal/balloon_target', String, self.on_balloon_gate, queue_size=5),
        ]
        self.worker = threading.Thread(target=self.loop, name='fm9g-frame-locator-worker')
        self.worker.start()
        self.audit(kind='ready', image_topic=self.image_topic, output=str(self.output))
        rospy.loginfo('MULTIMODAL_FRAME_READY evidence=%s image=%s', self.output, self.image_topic)

    def audit(self, **event):
        event.update(wall_time=datetime.now(timezone.utc).isoformat(), monotonic=time.monotonic())
        self.log.write(json.dumps(event, ensure_ascii=False) + '\n')

    def stop(self):
        self.stop_event.set()
        self.worker.join(timeout=2.0)

    def on_balloon_gate(self, _msg):
        # Any balloon-gate message (start or stop) means the mission has reached the
        # hit_balloon phase; square_frame identification only ever runs before that,
        # so this is a one-way latch, never re-armed.
        with self.lock:
            if self.active:
                self.active = False
                self.audit(kind='deactivated', reason='balloon_phase_started')
                rospy.loginfo('MULTIMODAL_FRAME_STOP (balloon phase started)')

    def on_image(self, msg):
        acquired = time.monotonic()
        header_stamp = msg.header.stamp.to_sec()
        stamp = header_stamp if header_stamp > 0 else rospy.Time.now().to_sec()
        with self.lock:
            if not self.active:
                return
        try:
            bgr = decode_bgr(msg)
        except Exception as exc:
            rospy.logwarn_throttle(2.0, 'MULTIMODAL_FRAME_IMAGE_ERROR %s', exc)
            return
        if msg.width != 640 or msg.height != 480:
            rospy.logerr_throttle(5.0, 'MULTIMODAL_FRAME_CAMERA_GEOMETRY_MISMATCH %sx%s', msg.width, msg.height)
            return
        with self.lock:
            if self.pending:
                return
            self.frame_seq += 1
            self.frame = (self.frame_seq, stamp, acquired, bgr)

    def loop(self):
        while not self.stop_event.wait(0.02):
            with self.lock:
                if not self.active or self.frame is None:
                    continue
                seq, stamp, acquired, bgr = self.frame
                self.frame = None
                self.pending = True
            decision = uuid.uuid4().hex[:12]
            image = PILImage.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            image_path = self.output / 'images' / (decision + '.png')
            image.save(image_path)
            self.audit(kind='model_source', decision=decision, frame_seq=seq, stamp=stamp,
                       acquired=acquired, image=str(image_path.relative_to(self.output)),
                       image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest())
            start = time.monotonic()
            try:
                box, p0 = self.localize(bgr, decision, seq, stamp)
            except Exception as exc:
                rospy.logwarn_throttle(2.0, 'MULTIMODAL_FRAME_INFER_ERROR %s', exc)
                box, p0 = None, 0.0
            latency = time.monotonic() - start
            self.audit(kind='decision', decision=decision, frame_seq=seq, box=box, p0=p0,
                       latency_s=latency)
            if box:
                self.publish(box, p0, bgr)
            with self.lock:
                self.pending = False

    def localize(self, bgr, decision, frame_seq, stamp):
        """Tile scan for a rough ROI, then a two-pass edge sweep -- identical control
        flow to NativePresenceSweep.acquire(), reimplemented here only because
        acquire() does not return the confidence score this module needs for
        Obj.score (and must not be modified in-place; see class docstring)."""
        p = self.presence
        tile = 224
        xs = np.linspace(0, 640 - tile, 5).astype(int)
        ys = np.linspace(0, 480 - tile, 3).astype(int)
        windows = [(int(x), int(y), int(x) + tile, int(y) + tile) for y in ys for x in xs]
        probs = p.call(p.crops(bgr, windows), PROMPT, self._epoch, decision, 'frame', 'frame',
                        frame_seq, stamp, 'acquire_tiles', windows)
        positive = [w for w, prob in zip(windows, probs) if prob >= 0.5]
        if not positive:
            return None, 0.0
        best = windows[int(np.argmax(probs))]
        group = [w for w in positive
                 if min(w[2], best[2]) > max(w[0], best[0]) and min(w[3], best[3]) > max(w[1], best[1])]
        roi = (max(w[0] for w in group), max(w[1] for w in group),
               min(w[2] for w in group), min(w[3] for w in group))
        if roi[2] - roi[0] < 48 or roi[3] - roi[1] < 48:
            roi = best
        for window in (
            p.square((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2,
                     max(roi[2] - roi[0], roi[3] - roi[1], 128)),
            tuple(best),
        ):
            images, positions = p.sweep_imgs(bgr, window, p.n_initial)
            probs = p.call(images, PROMPT, self._epoch, decision, 'frame', 'frame', frame_seq,
                            stamp, 'acquire_sweep', [window])
            box, p0, curves = p.edge_box(probs, positions, window, (0.5,) * 4)
            self.audit(kind='presence_sweep', decision=decision, frame_seq=frame_seq,
                       p0=p0, curves=curves, box=box, window=window, positions=positions)
            if box:
                return box, p0
        return None, 0.0

    def publish(self, box, score, bgr):
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        self.header_seq += 1
        objects = Objects()
        objects.header.stamp = rospy.Time.now()
        objects.header.seq = self.header_seq
        objects.source_id = SOURCE_ID_FRONT
        obj = Obj()
        obj.class_name = CLASS_NAME
        obj.left_top_x, obj.left_top_y = max(0, x1), max(0, y1)
        obj.right_bottom_x, obj.right_bottom_y = min(640, x2), min(480, y2)
        obj.center_x = (obj.left_top_x + obj.right_bottom_x) // 2
        obj.center_y = (obj.left_top_y + obj.right_bottom_y) // 2
        obj.score = float(score)
        obj.header = objects.header
        objects.objects.append(obj)
        self.objects_pub.publish(objects)
        self.publish_debug(bgr, box, score)

    def publish_debug(self, bgr, box, score):
        # Rule 4.4(5) requires a visible bbox-detection-result window; this mirrors
        # the balloon bridge's debug_pub pattern on its own topic so the two windows
        # don't collide.
        vis = bgr.copy()
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(vis, f'square_frame p={score:.2f}', (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        msg = Image()
        msg.header.stamp = rospy.Time.now()
        msg.height, msg.width = vis.shape[:2]
        msg.encoding = 'bgr8'
        msg.step = msg.width * 3
        msg.data = vis.tobytes()
        self.debug_pub.publish(msg)
