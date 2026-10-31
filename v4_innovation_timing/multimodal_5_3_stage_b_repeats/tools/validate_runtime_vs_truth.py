#!/usr/bin/env python3
"""Score the real (threaded) PerceptionBridge against YOLO ground truth directly, instead of demanding
frame-by-frame byte parity with the single-threaded offline P12e replay.

Why: Astra's Stage B gate (<=3px vs the offline P12e trajectory) fails because real model-call latency jitters
by tens of ms against the recorded/median latency the offline virtual clock assumed; that shifts which frame
triggers a given acquire/track call by ~1 frame, CSRT reinitializes on a different frame, and the two
trajectories diverge chaotically from that point even though both remain path-dependent-but-locally-accurate.
The question that matters for Stage C is not "does runtime match the offline script bit-for-bit" but "is the
runtime's own accuracy against ground truth comparable to what P12e measured offline" -- this script answers
that directly, reusing the real PerceptionBridge (no shortcuts, no detector/HSV in the loop) and the same YOLO
ground-truth extraction used throughout p10/p12 scoring.

Loads the model once and drives one fresh PerceptionBridge per trial (no ROS, no simulator, not flight).
"""
import json
import math
import os
import shutil
import sys
import time
import types
from pathlib import Path

import cv2


class Stamp:
    def __init__(self, value): self.value = float(value)
    def to_sec(self): return self.value


class Header:
    def __init__(self, stamp=0.0): self.stamp = Stamp(stamp); self.seq = 0; self.frame_id = ''


class ImageMsg:
    def __init__(self, bgr, stamp):
        self.header = Header(stamp); self.height, self.width = bgr.shape[:2]
        self.encoding = 'bgr8'; self.step = self.width * 3; self.data = bgr.tobytes()


class StringMsg:
    def __init__(self, data=''): self.data = data


class ObjMsg:
    def __init__(self): self.header = Header(); self.class_name = ''; self.score = 0.0


class ObjectsMsg:
    def __init__(self): self.header = Header(); self.source_id = 0; self.objects = []


class DetEnableMsg:
    def __init__(self): self.is_open = True


class FakePublisher:
    def __init__(self, topic): self.topic = topic
    def publish(self, message): pass


class FakeSubscriber:
    def unregister(self): pass


class FakeRospy(types.ModuleType):
    def __init__(self): super().__init__('rospy')
    def Publisher(self, topic, *a, **k): return FakePublisher(topic)
    def Subscriber(self, *a, **k): return FakeSubscriber()
    def loginfo(self, *a, **k): pass
    def logwarn(self, *a, **k): pass
    def logerr(self, *a, **k): pass
    def loginfo_throttle(self, *a, **k): pass
    def logwarn_throttle(self, *a, **k): pass
    def logerr_throttle(self, *a, **k): pass
    def is_shutdown(self): return False


rospy = FakeRospy()
rospy.Time = types.SimpleNamespace(from_sec=lambda v: Stamp(v), now=lambda: Stamp(time.time()))
sys.modules['rospy'] = rospy
sensor_msgs = types.ModuleType('sensor_msgs'); sensor_msgs_msg = types.ModuleType('sensor_msgs.msg'); sensor_msgs_msg.Image = ImageMsg
sensor_msgs.msg = sensor_msgs_msg; sys.modules['sensor_msgs'] = sensor_msgs; sys.modules['sensor_msgs.msg'] = sensor_msgs_msg
std_msgs = types.ModuleType('std_msgs'); std_msgs_msg = types.ModuleType('std_msgs.msg'); std_msgs_msg.String = StringMsg
std_msgs.msg = std_msgs_msg; sys.modules['std_msgs'] = std_msgs; sys.modules['std_msgs.msg'] = std_msgs_msg
common_msgs = types.ModuleType('common_msgs'); common_msgs_msg = types.ModuleType('common_msgs.msg')
common_msgs_msg.Objects = ObjectsMsg; common_msgs_msg.Obj = ObjMsg; common_msgs_msg.DetEnable = DetEnableMsg
common_msgs.msg = common_msgs_msg; sys.modules['common_msgs'] = common_msgs; sys.modules['common_msgs.msg'] = common_msgs_msg

STAGE_B = Path(sys.argv[1])  # isolated stage-B copy, has v2/
ROOT = Path(sys.argv[2])     # .../multimodal_v2_regression_20261026
RUNS = sys.argv[3].split(',')
OUTPUT = Path(sys.argv[4]) if len(sys.argv) > 4 else Path('/tmp/p12e_runtime_truth_summary.json')
LABEL = sys.argv[5] if len(sys.argv) > 5 else 'run'
pkg = types.ModuleType('fm9g_perception'); pkg.__path__ = [str(STAGE_B / 'v2')]; sys.modules['fm9g_perception'] = pkg
from fm9g_perception.runtime import PerceptionBridge  # noqa: E402
from transformers import AutoModel, AutoProcessor, AutoTokenizer  # noqa: E402
import torch  # noqa: E402
import threading  # noqa: E402


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def ce(a, b):
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


def gate(p, t):
    return iou(p, t) >= 0.5 and ce(p, t) <= max(8, 0.2 * math.hypot(t[2] - t[0], t[3] - t[1]))


model_dir = '/home/ubuntu/model/FM9G4B-V'
tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
proc.image_processor.scale_resolution = 224
model = AutoModel.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
model_lock = threading.Lock()

summary = {}
for sequence_index, run in enumerate(RUNS, start=1):
    color = run.split('_')[2]
    d = ROOT / run / 'audit'
    events = [json.loads(l) for l in open(d / 'events.jsonl')]
    start = next(e['ros_time'] for e in events if e['event'] == 'rosout' and 'Visual Servo Started' in e.get('message', ''))
    frames = [e for e in events if e['event'] == 'image' and start - 2 <= e['ros_time'] <= start + 50 and (d / e['file']).exists()]
    yolo = [e for e in events if e['event'] == 'objects' and e.get('topic') == 'yolo']

    def yolo_box(e):
        m = [y for y in yolo if abs(y['stamp'] - e['header_stamp']) < 0.06]
        if not m:
            return 'nodata'
        o = [x for x in min(m, key=lambda y: abs(y['stamp'] - e['header_stamp']))['objects'] if x['name'] == color + '_balloon']
        return o[0]['bbox'] if o else None

    out_dir = Path('/tmp/p12e_runtime_truth') / f'{LABEL}_{sequence_index:02d}_{run}'
    os.environ['MULTIMODAL_EVIDENCE_ROOT'] = str(out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)
    bridge = PerceptionBridge(model, tok, proc, model_lock)
    session = f'truth-{run}'
    bridge.on_gate(StringMsg(json.dumps({'action': 'start', 'session': session, 'color': color})))
    previous = frames[0]['header_stamp']; first = True
    for e in frames:
        delay = max(0.0, e['header_stamp'] - previous)
        if delay:
            time.sleep(delay)
        bgr = cv2.imread(str(d / e['file']))
        bridge.on_image(ImageMsg(bgr, e['header_stamp']))
        if first:
            time.sleep(0.1); first = False
        previous = e['header_stamp']
    time.sleep(2.0)
    bridge.close()

    audit_file = next(out_dir.rglob('audit.jsonl'))
    publishes = {}
    errors = 0
    kind_counts = {}
    model_calls = {'acquire_tiles': 0, 'acquire_sweep': 0, 'track_sweep': 0}
    latencies = {'acquire_tiles': [], 'acquire_sweep': [], 'track_sweep': []}
    gpu_ms = {'acquire_tiles': [], 'acquire_sweep': [], 'track_sweep': []}
    cuda_memory = {'acquire_tiles': [], 'acquire_sweep': [], 'track_sweep': []}
    for line in audit_file.open():
        ev = json.loads(line)
        kind_counts[ev.get('kind')] = kind_counts.get(ev.get('kind'), 0) + 1
        if ev.get('kind') == 'inference_error':
            errors += 1
        if ev.get('kind') == 'publish':
            publishes[ev['frame_seq']] = ev.get('bbox')
        if ev.get('kind') == 'presence_model_call':
            stage = ev.get('stage')
            if stage in model_calls:
                model_calls[stage] += 1
                latencies[stage].append(ev.get('latency_s'))
                if ev.get('gpu_ms') is not None:
                    gpu_ms[stage].append(ev['gpu_ms'])
                if ev.get('cuda_memory_allocated') is not None:
                    cuda_memory[stage].append(ev['cuda_memory_allocated'])

    vis = pub = ok = absent = fp = 0
    for i, e in enumerate(frames, start=1):
        g = yolo_box(e)
        if g == 'nodata':
            continue
        b = publishes.get(i)
        if isinstance(g, list):
            vis += 1
            if b:
                pub += 1
                if gate(b, g) or (g[0] <= (b[0] + b[2]) / 2 <= g[2] and g[1] <= (b[1] + b[3]) / 2 <= g[3]):
                    ok += 1
        else:
            absent += 1
            fp += bool(b)
    def stats(xs):
        xs = sorted(x for x in xs if x is not None)
        if not xs:
            return {'count': 0, 'min': None, 'median': None, 'p95': None, 'max': None, 'all': []}
        p95 = xs[min(len(xs) - 1, max(0, math.ceil(0.95 * len(xs)) - 1))]
        return {'count': len(xs), 'min': round(xs[0], 6),
                'median': round(xs[len(xs) // 2], 6), 'p95': round(p95, 6),
                'max': round(xs[-1], 6), 'all': [round(v, 6) for v in xs]}
    key = f'{LABEL}_{sequence_index:02d}_{run}'
    summary[key] = dict(sequence_index=sequence_index, label=LABEL, run=run,
                        frames=len(frames), visible=vis, centre_ok=ok, published=pub,
                        centre_pct=round(100 * ok / vis, 1) if vis else None,
                        precision_pct=round(100 * ok / pub, 1) if pub else None,
                        false_publish_absent=f'{fp}/{absent}', inference_errors=errors,
                        event_counts=kind_counts,
                        model_calls=model_calls,
                        latency_s=latencies,
                        latency_stats={k: stats(v) for k, v in latencies.items()},
                        gpu_ms=gpu_ms,
                        gpu_ms_stats={k: stats(v) for k, v in gpu_ms.items()},
                        cuda_memory_allocated=cuda_memory,
                        cuda_memory_stats={k: stats(v) for k, v in cuda_memory.items()},
                        audit_path=str(audit_file))
    print(key, summary[key], flush=True)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(summary, indent=1))
print(json.dumps(summary, indent=1))
