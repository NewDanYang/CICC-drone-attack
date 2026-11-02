"""SceneBridge: FM9G4B-V recognition + localisation of all non-balloon targets.

Runs inside mission_once.py next to the balloon bridge and shares its model.

Control contract (the only way results enter the mission):
  BT node Fm9gLocate publishes  /fm9g/scene_request  "start <target> <id>" / "stop <target> <id>"
  this bridge publishes          /fm9g/target_world/<target>  geometry_msgs/PointStamped (world ENU)
  Fm9gLocate collects N agreeing samples, writes the median to the blackboard,
  and the existing GoTo / PlanningControl nodes fly to it.

Per decision:  native <box> proposal (448 px, greedy)  ->  contrastive presence
verify on the crop (P(是) >= 0.7)  ->  metric position:
  front targets: depth camera (ring depth for the hollow frame) + odom at the image stamp,
                 and for the frame the box size must agree with that depth;
  down targets:  ray / ground-plane intersection + odom at the image stamp,
                 and the implied metric size must be plausible.
Only measurements that pass every gate are published.  No YOLO, HSV, colour
threshold or simulator truth is used anywhere in this path.
"""
import json
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import rospy
from geometry_msgs.msg import PointStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, PointCloud2
from std_msgs.msg import String

from . import geometry as geo
from .model_io import SceneModel
from .pipeline import localise, select_candidates
from .targets import TARGETS

COLORS = {'square_frame': (0, 255, 0), 'pillar': (0, 165, 255),
          'aruco_marker': (255, 0, 255), 'landing_pad': (255, 255, 0)}


def decode_bgr(msg):
    channels = {'rgb8': 3, 'bgr8': 3, 'rgba8': 4, 'bgra8': 4}.get(msg.encoding)
    if channels is None or len(msg.data) != msg.height * msg.step:
        raise ValueError('unsupported image %s' % msg.encoding)
    rows = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
    arr = rows[:, :msg.width * channels].reshape(msg.height, msg.width, channels)[:, :, :3]
    return (arr[:, :, ::-1] if msg.encoding.startswith('rgb') else arr).copy()


def decode_cloud(msg, stride=4):
    """xyz float32 points from a PointCloud2 without per-point Python loops."""
    offs = {f.name: f.offset for f in msg.fields}
    if not all(k in offs for k in 'xyz'):
        raise ValueError('cloud lacks xyz')
    n = msg.width * msg.height
    raw = np.frombuffer(msg.data, dtype=np.uint8)[:n * msg.point_step].reshape(n, msg.point_step)
    raw = raw[::stride]
    xyz = np.stack([raw[:, offs[k]:offs[k] + 4].copy().view('<f4')[:, 0] for k in 'xyz'], 1)
    return xyz[np.isfinite(xyz).all(1)].astype(float)


class SceneBridge:
    def __init__(self, model, tokenizer, processor, model_lock, fast_presence):
        self.lock = threading.RLock()
        self.log_lock = threading.Lock()
        self.stop_event = threading.Event()
        root = os.environ.get('FM9G_SCENE_EVIDENCE_ROOT',
                              '/home/ubuntu/tcei_baseline_tools/results/fm9g_scene')
        self.output = Path(root) / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_') + uuid.uuid4().hex[:6])
        (self.output / 'images').mkdir(parents=True)
        self.log = (self.output / 'audit.jsonl').open('w', encoding='utf-8', buffering=1)
        self.sm = SceneModel(model, tokenizer, processor, model_lock, self.audit, fast_presence)

        self.odom = deque(maxlen=400)
        self.images = {'front': None, 'down': None}
        self.last_used = {}            # (camera, target) -> image stamp already processed
        self.cloud = None
        self.request = None            # (target, id, start_stamp)
        self.balloon_phase = False
        self.result_seen = False
        self.idle_period = float(os.environ.get('FM9G_SCENE_IDLE_PERIOD', '3.0'))
        self.idle_targets = [t for t in os.environ.get('FM9G_SCENE_IDLE', 'pillar').split(',') if t]
        self.last_idle = 0.0
        self.display = None
        self.max_image_age = 0.6
        self.max_cloud_skew = 0.35

        odom_topic = rospy.get_param('~odom_topic', os.environ.get('FM9G_SCENE_ODOM', '/rflysim/uav1/local/odom'))
        self.pubs = {name: rospy.Publisher('/fm9g/target_world/' + name, PointStamped, queue_size=5)
                     for name in TARGETS}
        self.debug_pub = rospy.Publisher('/fm9g/scene_debug_image', Image, queue_size=1)
        self.subs = [
            rospy.Subscriber('/rflysim/sensor1/img_rgb', Image, self.on_image, 'front',
                             queue_size=1, buff_size=4 * 1024 * 1024),
            rospy.Subscriber('/rflysim/sensor2/img_rgb', Image, self.on_image, 'down',
                             queue_size=1, buff_size=4 * 1024 * 1024),
            rospy.Subscriber('/rflysim/sensor0/Depth_Cloud', PointCloud2, self.on_cloud,
                             queue_size=1, buff_size=16 * 1024 * 1024),
            rospy.Subscriber(odom_topic, Odometry, self.on_odom, queue_size=20),
            rospy.Subscriber('/fm9g/scene_request', String, self.on_request, queue_size=10),
            rospy.Subscriber('/multimodal/balloon_target', String, self.on_balloon, queue_size=5),
            rospy.Subscriber('/mission_result', String, self.on_result, queue_size=2),
        ]
        self.threads = [threading.Thread(target=self.loop, name='fm9g-scene-worker')]
        if os.environ.get('FM9G_SCENE_WINDOW', '1') == '1':
            self.threads.append(threading.Thread(target=self.window_loop, name='fm9g-scene-window'))
        for t in self.threads:
            t.daemon = True
            t.start()
        self.audit(kind='ready', output=str(self.output), odom_topic=odom_topic,
                   targets=sorted(TARGETS), idle=self.idle_targets, pid=os.getpid())
        rospy.loginfo('FM9G_SCENE_READY evidence=%s', self.output)

    # ------------------------------------------------------------------ io
    def audit(self, **event):
        event.update(wall_time=datetime.now(timezone.utc).isoformat(), monotonic=time.monotonic())
        with self.log_lock:
            self.log.write(json.dumps(event, ensure_ascii=False, default=float) + '\n')

    def close(self):
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=2.0)

    # Clocks: every buffered message keeps (header stamp, ROS receive time).
    # Freshness, "captured after the request" and the published stamp use the
    # receive time, i.e. the same ROS clock as Fm9gLocate's ros::Time::now(),
    # so a camera/sim clock that differs from ROS time cannot make every sample
    # look stale or pre-request.  Pose/depth matching prefers header stamps and
    # falls back to receive times; the audit records which clock matched.
    @staticmethod
    def header_of(msg):
        return msg.header.stamp.to_sec()

    def on_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        with self.lock:
            self.odom.append((self.header_of(msg), rospy.Time.now().to_sec(),
                              np.array([p.x, p.y, p.z]), geo.quat_to_R(q.x, q.y, q.z, q.w)))

    def on_image(self, msg, camera):
        if msg.width != geo.IMAGE_W or msg.height != geo.IMAGE_H:
            rospy.logerr_throttle(5.0, 'FM9G_SCENE camera %s geometry %sx%s', camera, msg.width, msg.height)
            return
        with self.lock:
            self.images[camera] = (self.header_of(msg), rospy.Time.now().to_sec(), msg)   # decode lazily

    def on_cloud(self, msg):
        with self.lock:
            self.cloud = (self.header_of(msg), rospy.Time.now().to_sec(), msg)

    def on_request(self, msg):
        parts = msg.data.split()
        if len(parts) < 2 or parts[1] not in TARGETS:
            rospy.logwarn('FM9G_SCENE bad request %r', msg.data)
            return
        with self.lock:
            rid = parts[2] if len(parts) > 2 else ''
            if parts[0] == 'start':
                if self.request and self.request[:2] == (parts[1], rid):
                    return          # periodic re-send from the BT node; keep the original start time
                self.request = (parts[1], rid, rospy.Time.now().to_sec())
            elif parts[0] == 'stop' and self.request and self.request[0] == parts[1]:
                self.request = None
        self.audit(kind='request', data=msg.data)
        rospy.loginfo('FM9G_SCENE request: %s', msg.data)

    def on_balloon(self, _msg):
        with self.lock:
            if not self.balloon_phase:
                self.balloon_phase = True
                self.audit(kind='idle_off', reason='balloon_phase_started')

    def on_result(self, msg):
        self.result_seen = True
        self.audit(kind='mission_result', data=msg.data[:500])

    @staticmethod
    def nearest(items, header, recv, header_tol, recv_tol):
        """Nearest buffered item by header stamp, else by receive time."""
        if not items:
            return None, None
        if header > 0:
            best = min(items, key=lambda o: abs(o[0] - header))
            if best[0] > 0 and abs(best[0] - header) <= header_tol:
                return best, 'header'
        best = min(items, key=lambda o: abs(o[1] - recv))
        if abs(best[1] - recv) <= recv_tol:
            return best, 'receive'
        return None, None

    def pose_at(self, header, recv):
        with self.lock:
            odom = list(self.odom)
        best, clock = self.nearest(odom, header, recv, 0.2, 0.1)
        return (None, None) if best is None else ((best[2], best[3]), clock)

    # --------------------------------------------------------------- worker
    def loop(self):
        while not self.stop_event.wait(0.02):
            with self.lock:
                req = self.request
                idle = (req is None and not self.balloon_phase and self.idle_targets and
                        time.monotonic() - self.last_idle > self.idle_period)
            try:
                if req is not None:
                    self.step(TARGETS[req[0]], req)
                elif idle:
                    self.last_idle = time.monotonic()
                    for name in self.idle_targets:
                        self.step(TARGETS[name], None)
            except Exception as exc:   # never let perception kill the mission process
                rospy.logwarn_throttle(2.0, 'FM9G_SCENE error %s', exc)
                self.audit(kind='error', error=repr(exc))
                time.sleep(0.2)

    def step(self, spec, req):
        with self.lock:
            item = self.images[spec.camera]
        if item is None:
            return
        header, stamp, msg = item          # stamp = ROS receive time
        key = (spec.camera, spec.name)
        with self.lock:
            if self.last_used.get(key) == stamp:
                return              # one image -> at most one measurement per target
            self.last_used[key] = stamp
        now = rospy.Time.now().to_sec()
        if now - stamp > self.max_image_age or (req is not None and stamp < req[2]):
            return
        pose, pose_clock = self.pose_at(header, stamp)
        if pose is None:
            rospy.logwarn_throttle(2.0, 'FM9G_SCENE no odom near image stamp')
            return
        bgr = decode_bgr(msg)
        decision = uuid.uuid4().hex[:12]
        path = self.output / 'images' / (decision + '.jpg')
        cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        self.audit(kind='model_source', decision=decision, target=spec.name,
                   request=req[1] if req else None, stamp=stamp, header_stamp=header,
                   pose_clock=pose_clock, image=path.name, pose=pose[0].tolist())

        native = self.sm.native_boxes(bgr, spec, decision)
        boxes = [geo.native_to_pixels(b) for b in native]
        probs = self.sm.verify(bgr, boxes, spec, decision)
        results = []
        cloud_pts = None
        if spec.camera == 'front':
            with self.lock:
                cloud = self.cloud
            match, _ = self.nearest([cloud] if cloud else [], header, stamp,
                                    self.max_cloud_skew, self.max_cloud_skew)
            if match is not None:
                cloud_pts = decode_cloud(match[2])
        for box, p in select_candidates(spec, boxes, probs):
            results.append(localise(spec, box, p, pose[0], pose[1], cloud_pts))
        self.audit(kind='decision', decision=decision, target=spec.name,
                   n_native=len(native), probs=probs, results=results)
        for r in results:
            if r['accepted']:
                self.publish(spec.name, r['world'], stamp)
        self.show(bgr, spec, boxes, probs, results)

    def publish(self, name, world, stamp):
        msg = PointStamped()
        msg.header.stamp = rospy.Time.from_sec(stamp)
        msg.header.frame_id = 'world'
        msg.point.x, msg.point.y, msg.point.z = world
        self.pubs[name].publish(msg)

    # -------------------------------------------------------------- display
    def show(self, bgr, spec, boxes, probs, results):
        vis = bgr.copy()
        for box, p in zip(boxes, probs):
            x1, y1, x2, y2 = [int(round(v)) for v in box]
            cv2.rectangle(vis, (x1, y1), (x2, y2), (128, 128, 128), 1)
        for r in results:
            x1, y1, x2, y2 = [int(round(v)) for v in r['box']]
            color = COLORS.get(spec.name, (0, 255, 0)) if r['accepted'] else (0, 0, 255)
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            label = '%s %.2f' % (spec.name, r['score'])
            if r['accepted']:
                label += ' (%.2f,%.2f,%.2f)' % tuple(r['world'])
            else:
                label += ' X ' + r.get('reject', '')
            cv2.putText(vis, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        cv2.putText(vis, 'FM9G4B-V %s camera=%s' % (spec.name, spec.camera), (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        out = Image()
        out.header.stamp = rospy.Time.now()
        out.height, out.width = vis.shape[:2]
        out.encoding, out.step = 'bgr8', vis.shape[1] * 3
        out.data = vis.tobytes()
        self.debug_pub.publish(out)
        with self.lock:
            self.display = vis

    def window_loop(self):
        """imshow lives on its own thread so a stalled X server cannot block
        inference or ROS callbacks (cf. AGENTS.md §5.2 hypothesis 1)."""
        name = 'FM9G scene perception'
        while not self.stop_event.wait(0.05):
            with self.lock:
                vis = self.display
            if vis is not None:
                cv2.imshow(name, vis)
            cv2.waitKey(1)
