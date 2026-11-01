#!/usr/bin/env python3
"""Replay the REAL saved source frames from a real closed-loop trial through two track-sweep window policies,
to see whether a 'grow aggressively when multiple edges fail to cross' fix would have kept the box sized
correctly as the real balloon grows during final approach. Uses the actual deployed FastPresence model and
sweep logic (not a re-derivation from logged curves), on the actual PNGs the real trial saw -- no synthetic
data, no flight, no ROS.
"""
import json, sys
from pathlib import Path
import cv2, numpy as np, torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer
sys.path.insert(0, str(Path(__file__).parent))
from fastpresence import FastPresence

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
AUDIT_DIR = Path(sys.argv[1])      # e.g. /home/ubuntu/tcei_baseline_tools/results/multimodal_v2/<ts>
START_FRAME_SEQ = int(sys.argv[2])  # frame_seq of the real 'acquire' decision whose box we seed from
END_T = float(sys.argv[3])          # stop replay this many seconds after the seed frame's wall time
COLOR = sys.argv[4]
OUT = Path(sys.argv[5])
RES = 224
N = 8
WF = 2.2
TH = (0.4, 0.5, 0.5, 0.4)
GRAY = 128

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fp = FastPresence(model, tok, proc, res=RES)
text = f"这张图片里有没有{CN[COLOR]}的气球？只回答“是”或“否”。"


def crops(frame, wins):
    return torch.stack([torch.nn.functional.interpolate(frame[w[1]:w[3], w[0]:w[2]].permute(2, 0, 1)[None].float(), size=(RES, RES),
                        mode="bilinear", align_corners=False)[0].permute(1, 2, 0).round().clamp(0, 255).byte() for w in wins])


def square(cx, cy, side, w=640, h=480):
    s = int(min(max(side, 32), h))
    a = int(round(min(max(cx - s / 2, 0), w - s))); b = int(round(min(max(cy - s / 2, 0), h - s)))
    return a, b, a + s, b + s


def sweep(frame, W):
    c = crops(frame, [W])[0]; S = W[2] - W[0]
    pos = list(np.linspace(0, S, N + 2)[1:-1]); imgs = [c]
    for d in "LRTB":
        for q in pos:
            m = c.clone(); q = int(round(q * RES / S))
            if d == "L": m[:, :q] = GRAY
            if d == "R": m[:, RES - q:] = GRAY
            if d == "T": m[:q, :] = GRAY
            if d == "B": m[RES - q:, :] = GRAY
            imgs.append(m)
    ps = fp(torch.stack(imgs), text)
    p0 = ps[0]; xs = [0.0] + pos
    edges = []
    for k in range(4):
        prof = [p0] + ps[1 + k * N:1 + (k + 1) * N]; t = TH[k] * p0; v = None
        for j in range(1, len(prof)):
            if prof[j - 1] >= t > prof[j]:
                a = (prof[j - 1] - t) / (prof[j - 1] - prof[j] + 1e-9); v = xs[j - 1] + a * (xs[j] - xs[j - 1]); break
        edges.append(v)
    return p0, edges, S


def sweep_with_retry(frame, cx, cy, side, policy):
    """One bounded retry, self-contained per call (no cross-call state): if the first sweep has >=2 edges
    that never cross (target extends past the window on multiple sides), widen once to 2x and re-sweep."""
    W = square(cx, cy, side)
    p0, edges, S = sweep(frame, W)
    if policy == "grow" and p0 >= 0.5 and sum(e is None for e in edges) >= 2 and side < 400:
        W2 = square(cx, cy, min(400, 2.0 * side))
        p0b, edges2, S2 = sweep(frame, W2)
        if p0b >= 0.5:
            return p0b, edges2, S2, W2, True
    return p0, edges, S, W, False


def box_from_edges(W, edges, S, prev_box, policy, retried=False):
    cL, cR, cT, cB = edges
    noncross = sum(e is None for e in edges)
    trust_window = policy == "grow" and retried and noncross >= 1
    if trust_window:
        nb = [W[0] + S - cR if cR is not None else W[0], W[1] + S - cB if cB is not None else W[1],
              W[0] + cL if cL is not None else W[2], W[1] + cT if cT is not None else W[3]]
    else:
        nb = [W[0] + S - cR if cR is not None else prev_box[0], W[1] + S - cB if cB is not None else prev_box[1],
              W[0] + cL if cL is not None else prev_box[2], W[1] + cT if cT is not None else prev_box[3]]
    if nb[2] <= nb[0] + 2 or nb[3] <= nb[1] + 2:
        return list(prev_box), noncross
    pw, ph = prev_box[2] - prev_box[0], prev_box[3] - prev_box[1]
    w, h = nb[2] - nb[0], nb[3] - nb[1]
    if not trust_window:
        w = min(max(w, 0.85 * pw), 1.25 * pw); h = min(max(h, 0.85 * ph), 1.25 * ph)
    cx, cy = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
    w, h = max(w, 12.0), max(h, 12.0)
    if h < 0.9 * w: cy, h = cy - (0.9 * w - h) / 2, 0.9 * w
    if h > 1.6 * w: w = h / 1.6
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], noncross


ev = [json.loads(l) for l in open(AUDIT_DIR / "audit.jsonl", encoding="utf-8")]
decs = {e["decision"]: e for e in ev if e.get("kind") == "decision"}
srcs = {e["decision"]: e for e in ev if e.get("kind") == "model_source"}
seed_dec = next(e for e in decs.values() if srcs.get(e["decision"], {}).get("frame_seq") == START_FRAME_SEQ)
seed_box = seed_dec["bbox"]
import datetime
t_seed = datetime.datetime.fromisoformat(srcs[seed_dec["decision"]]["wall_time"]).timestamp()

real_decs = sorted([d for d in decs.values() if d.get("mode") in ("track", "acquire") and d.get("bbox")
                    and srcs.get(d["decision"])], key=lambda d: srcs[d["decision"]]["frame_seq"])
real_decs = [d for d in real_decs if srcs[d["decision"]]["frame_seq"] >= START_FRAME_SEQ]
real_decs = [d for d in real_decs if datetime.datetime.fromisoformat(srcs[d["decision"]]["wall_time"]).timestamp() - t_seed <= END_T]

print(f"replaying {len(real_decs)} real decision frames from frame_seq={START_FRAME_SEQ}, seed box={seed_box}")

results = {"baseline": [], "grow": []}
for policy in ("baseline", "grow"):
    box = list(seed_box)
    for d in real_decs:
        src = srcs[d["decision"]]
        t = datetime.datetime.fromisoformat(src["wall_time"]).timestamp() - t_seed
        img_path = AUDIT_DIR / src["image"]
        bgr = cv2.imread(str(img_path))
        frame = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        side = max(56, WF * max(box[2] - box[0], box[3] - box[1]))
        p0, edges, S, W, retried = sweep_with_retry(frame, cx, cy, side, policy)
        if p0 < 0.5:
            results[policy].append(dict(t=t, box=None, window=W, window_side=S, noncross=4, p0=p0, retried=retried))
            continue
        newbox, noncross = box_from_edges(W, edges, S, box, policy, retried)
        box = newbox
        results[policy].append(dict(t=t, box=[round(x, 1) for x in box], window=W, window_side=S, p0=round(p0, 2), noncross=noncross, retried=retried))
        print(f"[{policy}] t={t:6.2f} window_side={S:4d} p0={p0:.2f} noncross={noncross} retried={retried} box_w={box[2]-box[0]:.0f} box_h={box[3]-box[1]:.0f}", flush=True)

OUT.write_text(json.dumps(results, indent=1))
