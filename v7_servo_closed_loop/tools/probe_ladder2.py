import sys, time, threading
sys.path.insert(0, '/home/ubuntu/model')
sys.path.insert(0, '/tmp/v7test')
import cv2, torch
from transformers import AutoModel, AutoTokenizer, AutoProcessor
MODEL = '/home/ubuntu/model/FM9G4B-V'
tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True,
                                 attn_implementation='sdpa',
                                 torch_dtype=torch.bfloat16).eval().cuda()
proc = getattr(model, 'processor', None) or AutoProcessor.from_pretrained(
    MODEL, trust_remote_code=True, local_files_only=True)
torch.set_num_threads(2)
torch.set_num_interop_threads(1)
import presence
events = []
def audit(**kw):
    events.append(kw)
sw = presence.NativePresenceSweep(model, tok, proc, threading.Lock(), audit,
                                 active=lambda e: True)
text = '这张图片里有没有紫色的气球？只回答“是”或“否”。'
B = '/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/'
CASES = [
 ('20261102T061338_729c64', '5a69c6035abb', [276.6,224.8,309.6,255.2], (290.0,240.0), (206.0,245.0), [156,217,206,278]),
 ('20261102T061338_729c64', '55a74990430d', [276.6,224.8,309.6,255.2], (290.0,240.0), (72.0,253.0), [26,203,117,303]),
 ('20261102T035020_b7d689', '94006fba74cd', [303.9,205.4,342.5,275.0], (260.0,320.0), (240.0,330.0), [131,140,346,422]),
]
def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua
for run, name, prev, center, alt, gt in CASES:
    img = cv2.imread(B + run + '/images/' + name + '.png')
    for minside in (120.0, 200.0):
        sw.min_track_side = minside
        events.clear()
        t0 = time.monotonic()
        box = sw.track(img, text, prev, 1, 'dbg', 'sess', 'purple', 0, time.time(),
                       center=center, side=150.0, max_growth=2.2, alt_center=alt)
        dt = time.monotonic() - t0
        tags = [(e.get('tag'), e.get('attempt'), round(float(e.get('p0') or 0), 2),
                 bool(any(e.get('saturated') or []))) for e in events
                if e.get('kind') == 'presence_sweep']
        print('%-16s %s min=%-5.0f box=%s IoU=%.2f t=%.2fs' % (
              name, run[-6:], minside,
              None if box is None else [round(v) for v in box],
              0.0 if box is None else iou(box, gt), dt), flush=True)
        print('     sweeps', tags, flush=True)