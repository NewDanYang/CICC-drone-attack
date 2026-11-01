#!/usr/bin/env python3
"""Replay ALL real decision frames (not a hand-picked sub-window) from a real closed-loop trial through two
track() policies (baseline vs tightened bounded-retry), scored against an HSV tight-colour-mask ground truth
computed independently per frame. This is the real-closed-loop counterpart of the offline 9-trial matrix,
using actual FM9G-driven trajectories instead of old YOLO-driven ones.
"""
import json, math, sys
from pathlib import Path
import cv2, numpy as np, torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer
sys.path.insert(0, str(Path(__file__).parent))
from fastpresence import FastPresence

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
HUE = {"red": [(0, 8), (170, 179)], "purple": [(138, 165)], "blue": [(108, 130)]}
AUDIT_DIR = Path(sys.argv[1])
COLOR = sys.argv[2]
OUT = Path(sys.argv[3])
RES, N, WF, TH, GRAY = 224, 8, 2.2, (0.4, 0.5, 0.5, 0.4), 128

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fp = FastPresence(model, tok, proc, res=RES)
text = f"这张图片里有没有{CN[COLOR]}的气球？只回答“是”或“否”。"


def hsv_box(bgr):
    h = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV); m = np.zeros(h.shape[:2], np.uint8)
    for lo, hi in HUE[COLOR]:
        m |= cv2.inRange(h, (lo, 90, 30), (hi, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m, 8)
    c = [st[i] for i in range(1, n) if st[i, 4] >= 20]
    if not c:
        return None
    s = max(c, key=lambda s: s[4]); return [int(s[0]), int(s[1]), int(s[0] + s[2]), int(s[1] + s[3])]


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


def track_once(frame, box, policy):
    """One call (baseline) or bounded-retry call (tight), mirrors the production track() shapes."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    side = max(56, WF * max(box[2] - box[0], box[3] - box[1]))
    W = square(cx, cy, side)
    p0, edges, S = sweep(frame, W)
    if p0 < 0.5:
        return None
    retried = False
    if policy in ("tight", "conf") and sum(e is None for e in edges) >= 2 and side < 400:
        side2 = min(400, 2.0 * side); W2 = square(cx, cy, side2)
        p0b, edges2, S2 = sweep(frame, W2)
        conf_ok = p0b >= (0.75 if policy == "conf" else 0.5)
        if conf_ok:
            W, edges, p0, S = W2, edges2, p0b, side2; retried = True
    cL, cR, cT, cB = edges
    trust = policy in ("tight", "conf") and retried and sum(e is None for e in edges) >= 2
    if trust:
        nb = [W[0] + S - cR if cR is not None else W[0], W[1] + S - cB if cB is not None else W[1],
              W[0] + cL if cL is not None else W[2], W[1] + cT if cT is not None else W[3]]
    else:
        nb = [W[0] + S - cR if cR is not None else box[0], W[1] + S - cB if cB is not None else box[1],
              W[0] + cL if cL is not None else box[2], W[1] + cT if cT is not None else box[3]]
    if nb[2] <= nb[0] + 2 or nb[3] <= nb[1] + 2:
        return list(box)
    pw, ph = box[2] - box[0], box[3] - box[1]; w, h = nb[2] - nb[0], nb[3] - nb[1]
    if not trust:
        w = min(max(w, 0.85 * pw), 1.25 * pw); h = min(max(h, 0.85 * ph), 1.25 * ph)
    cx, cy = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
    w, h = max(w, 12.0), max(h, 12.0)
    if h < 0.9 * w: cy, h = cy - (0.9 * w - h) / 2, 0.9 * w
    if h > 1.6 * w: w = h / 1.6
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


ev = [json.loads(l) for l in open(AUDIT_DIR / "audit.jsonl", encoding="utf-8")]
decs = [e for e in ev if e.get("kind") == "decision" and e.get("mode") in ("track", "acquire") and e.get("bbox")]
srcs = {e["decision"]: e for e in ev if e.get("kind") == "model_source"}
decs = sorted([d for d in decs if d["decision"] in srcs], key=lambda d: srcs[d["decision"]]["frame_seq"])
# Pure track()-only runs: seed from the FIRST track decision's own real box (already correctly placed by the
# real system), replay forward through CONSECUTIVE track decisions only. Stop a run at any acquire (which in
# the real system followed a lost target / search-phase camera pan -- a different regime this fix doesn't
# target) or at a gap of >1 real frame between a decision and the one source frame index later (a skipped
# step means the real system itself discarded that frame, usually also search-phase).
runs, cur = [], []
for d in decs:
    fs = srcs[d["decision"]]["frame_seq"]
    if d["mode"] == "acquire":
        if len(cur) >= 2:
            runs.append(cur)
        cur = []
        continue
    if cur and fs - cur[-1][0] > 15:  # real system skipped too much time: likely a camera-pan discontinuity
        if len(cur) >= 2:
            runs.append(cur)
        cur = []
    cur.append((fs, srcs[d["decision"]]["image"], d["bbox"]))
if len(cur) >= 2:
    runs.append(cur)
print(f"{len(decs)} real decision frames with a bbox, {len(runs)} pure-track runs "
      f"(lengths {[len(r) for r in runs]})", flush=True)
segments = runs

results = {"baseline": [], "tight": [], "conf": []}
for policy in ("baseline", "tight", "conf"):
    for seg in segments:
        box = list(seg[0][2])  # seed from this run's OWN first real track() box (already correctly placed)
        for fs, img_rel, real_box in seg[1:]:  # only score the subsequent track() steps
            bgr = cv2.imread(str(AUDIT_DIR / img_rel))
            frame = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
            newbox = track_once(frame, box, policy)
            gt = hsv_box(bgr)
            box = newbox if newbox else box
            row = dict(frame_seq=fs, box=[round(x, 1) for x in box] if newbox else None, gt=gt)
            if newbox and gt:
                b = newbox
                ix = max(0, min(b[2], gt[2]) - max(b[0], gt[0])); iy = max(0, min(b[3], gt[3]) - max(b[1], gt[1]))
                inter = ix * iy; union = (b[2] - b[0]) * (b[3] - b[1]) + (gt[2] - gt[0]) * (gt[3] - gt[1]) - inter
                iou = inter / union if union else 0
                ce = math.hypot((b[0] + b[2] - gt[0] - gt[2]) / 2, (b[1] + b[3] - gt[1] - gt[3]) / 2)
                cin = bool(gt[0] <= (b[0] + b[2]) / 2 <= gt[2] and gt[1] <= (b[1] + b[3]) / 2 <= gt[3])
                row.update(iou=round(iou, 3), ce=round(ce, 1), cin=cin, area_ratio=round(((b[2]-b[0])*(b[3]-b[1]))/((gt[2]-gt[0])*(gt[3]-gt[1])), 3))
            results[policy].append(row)
            print(f"[{policy}] fs={fs} box={row.get('box')} gt={gt} iou={row.get('iou')} cin={row.get('cin')} area_ratio={row.get('area_ratio')}", flush=True)

OUT.write_text(json.dumps(results, indent=1))
for policy in ("baseline", "tight"):
    rs = [r for r in results[policy] if "iou" in r]
    if rs:
        print(f"{policy}: n={len(rs)} cin={sum(r['cin'] for r in rs)}/{len(rs)} iou50={sum(r['iou']>=0.5 for r in rs)} "
              f"area_ratio_med={sorted(r['area_ratio'] for r in rs)[len(rs)//2]:.2f}")
