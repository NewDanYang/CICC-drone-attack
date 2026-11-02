import sys, time, threading, json
sys.path.insert(0, '/home/ubuntu/model')
sys.path.insert(0, '/tmp/v7test')
import cv2, numpy as np, torch
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
print('module', presence.__file__, flush=True)
NativePresenceSweep = presence.NativePresenceSweep
events = []
def audit(**kw):
    events.append(kw)
sw = NativePresenceSweep(model, tok, proc, threading.Lock(), audit,
                         active=lambda e: True)
text = '这张图片里有没有紫色的气球？只回答“是”或“否”。'
RUN = '/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261102T061338_729c64'
for name, center, alt in (('5a69c6035abb', (290.0, 240.0), (206.0, 245.0)),
                          ('55a74990430d', (290.0, 240.0), (72.0, 253.0))):
    img = cv2.imread(RUN + '/images/' + name + '.png')
    events.clear()
    t0 = time.monotonic()
    box = sw.track(img, text, [276.6, 224.8, 309.6, 255.2], 1, 'dbg',
                   'sess', 'purple', 0, time.time(), center=center, side=150.0,
                   max_growth=2.2, alt_center=alt)
    dt = time.monotonic() - t0
    print('===', name, 'box', None if box is None else [round(v, 1) for v in box],
          'elapsed', round(dt, 2), flush=True)
    for e in events:
        if e.get('kind') == 'presence_sweep':
            print('   sweep tag', e.get('tag'), 'attempt', e.get('attempt'),
                  'p0', round(float(e.get('p0') or 0), 3),
                  'win', [round(v) for v in e.get('window')], flush=True)