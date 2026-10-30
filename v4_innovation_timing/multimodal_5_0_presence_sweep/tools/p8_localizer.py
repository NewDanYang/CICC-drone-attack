#!/usr/bin/env python3
"""P7: occlusion-sweep localizer on the GPU fast path, zero-shot base FM9G4B-V. Records raw profiles for offline
threshold calibration (fit on 'train' frames, which the base model never saw; check on validation; report run10 test).

usage: p7_localizer.py OUT RES [splits]
"""
import json, math, statistics, sys, time
from pathlib import Path
import cv2, numpy as np, torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer
sys.path.insert(0, str(Path(__file__).parent))
from fastpresence import FastPresence

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=False)
RES = int(sys.argv[2])
SPLITS = sys.argv[3].split(",") if len(sys.argv) > 3 else ["train", "validation", "test"]
N1, N2 = 8, 10
GRAY = 128


def yesno(c):
    return f"这张图片里有没有{CN[c]}的气球？只回答“是”或“否”。"


tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fp = FastPresence(model, tok, proc, res=RES)
fp_full = FastPresence(model, tok, proc, res=448)


def sync():
    torch.cuda.synchronize(); return time.perf_counter()


def square(cx, cy, side, w=640, h=480):
    s = int(min(max(side, 32), h))
    a = int(round(min(max(cx - s / 2, 0), w - s))); b = int(round(min(max(cy - s / 2, 0), h - s)))
    return a, b, a + s, b + s


def crops(frame, wins):
    return torch.stack([torch.nn.functional.interpolate(frame[w[1]:w[3], w[0]:w[2]].permute(2, 0, 1)[None].float(),
                                                        size=(RES, RES), mode="bilinear", align_corners=False)[0]
                        .permute(1, 2, 0).round().clamp(0, 255).byte() for w in wins])


def sweep_batch(frame, W, n):
    """frame uint8 [480,640,3] cuda RGB. returns images [4n+1] (index 0 = unmasked) and positions (window px)."""
    c = crops(frame, [W])[0]; S = W[2] - W[0]
    pos = np.linspace(0, S, n + 2)[1:-1]
    qs = [int(round(q * RES / S)) for q in pos]
    imgs = [c]
    for d in "LRTB":
        for q in qs:
            m = c.clone()
            if d == "L": m[:, :q] = GRAY
            if d == "R": m[:, RES - q:] = GRAY
            if d == "T": m[:q, :] = GRAY
            if d == "B": m[RES - q:, :] = GRAY
            imgs.append(m)
    return torch.stack(imgs), list(pos)


def edges(ps, pos, S, thr=0.5):
    """ps[0] unmasked, then L,R,T,B profiles. crossing at thr*p0 (relative). returns window-local x0,y0,x1,y1."""
    p0 = ps[0]; n = len(pos); out = []
    for k in range(4):
        prof = [p0] + ps[1 + k * n:1 + (k + 1) * n]; xs = [0.0] + pos; t = thr * p0; v = float(S)
        for j in range(1, len(prof)):
            if prof[j - 1] >= t > prof[j]:
                a = (prof[j - 1] - t) / (prof[j - 1] - prof[j] + 1e-9); v = xs[j - 1] + a * (xs[j] - xs[j - 1]); break
        out.append(v)
    cL, cR, cT, cB = out
    return [S - cR, S - cB, cL, cT]


def localize(frame, color, rec):
    text = yesno(color); t0 = sync()
    rec["p_full"] = fp_full(frame[None], text)[0]; t1 = sync()
    TW = 224; xs = np.linspace(0, 640 - TW, 5).astype(int); ys = np.linspace(0, 480 - TW, 3).astype(int)
    wins = [(int(x), int(y), int(x) + TW, int(y) + TW) for y in ys for x in xs]
    pt = fp(crops(frame, wins), text); rec["p_tiles"] = pt; t2 = sync()
    rec.update(t_full=t1 - t0, t_tiles=t2 - t1)
    on = [w for w, p in zip(wins, pt) if p >= 0.5]
    if not on:
        return
    # ROI = intersection of the positive tiles that overlap the strongest tile (the target lies in all of them)
    k = int(np.argmax(pt)); best = wins[k]
    grp = [w for w in on if min(w[2], best[2]) > max(w[0], best[0]) and min(w[3], best[3]) > max(w[1], best[1])]
    roi = (max(w[0] for w in grp), max(w[1] for w in grp), min(w[2] for w in grp), min(w[3] for w in grp))
    if roi[2] - roi[0] < 48 or roi[3] - roi[1] < 48:
        roi = best
    rec["roi"] = roi
    W1 = square((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2, max(roi[2] - roi[0], roi[3] - roi[1], 128)); rec["W1"] = W1
    imgs, pos1 = sweep_batch(frame, W1, N1); ps1 = fp(imgs, text); t3 = sync()
    e = edges(ps1, pos1, W1[2] - W1[0]); rec.update(ps1=ps1, pos1=pos1, t_s1=t3 - t2)
    cx, cy = W1[0] + (e[0] + e[2]) / 2, W1[1] + (e[1] + e[3]) / 2
    side = max(64, 2.5 * max(e[2] - e[0], e[3] - e[1], 16))
    if (ps1[0] < 0.5 or e[2] <= e[0] or e[3] <= e[1]) and W1 != tuple(best):
        rec["s1_retry"] = True; W1 = tuple(best); rec["W1"] = W1
        imgs, pos1 = sweep_batch(frame, W1, N1); ps1 = fp(imgs, text); t3 = sync()
        e = edges(ps1, pos1, W1[2] - W1[0]); rec.update(ps1=ps1, pos1=pos1, t_s1=t3 - t2)
        cx, cy = W1[0] + (e[0] + e[2]) / 2, W1[1] + (e[1] + e[3]) / 2
        side = max(64, 2.5 * max(e[2] - e[0], e[3] - e[1], 16))
    if ps1[0] < 0.5 or e[2] <= e[0] or e[3] <= e[1]:
        rec["s1_invalid"] = True; cx, cy, side = (W1[0] + W1[2]) / 2, (W1[1] + W1[3]) / 2, W1[2] - W1[0]
    W2 = square(cx, cy, side); rec["W2"] = W2
    imgs, pos2 = sweep_batch(frame, W2, N2); ps2 = fp(imgs, text); t4 = sync()
    rec.update(ps2=ps2, pos2=pos2, t_s2=t4 - t3, t_total=t4 - t0)
    # semantic cross-check on the fine window for the other two colours
    others = [c for c in CN if c != color]
    c2 = crops(frame, [W2]).repeat(2, 1, 1, 1)
    rec["cross"] = dict(zip(others, fp(c2, [yesno(o) for o in others]))); rec["t_cross"] = sync() - t4


cases = {c["id"]: c for d in ("mm40_spatial_clean", "mm41_run8_mix")
         for c in json.loads(Path(f"/root/gpufree-data/{d}/data/cases.json").read_text())}
hsv = {}
for f in ("p1_mm40.json", "p1_mm41.json"):
    for r in json.loads(Path(f"/root/gpufree-data/fm_research/{f}").read_text()):
        if r.get("hsv") and r["iou"] >= 0.3:
            hsv[r["id"]] = r["hsv"]
ids = sorted(i for i, c in cases.items() if c["split"] in SPLITS and (not c["present"] or i in hsv))
w0 = torch.from_numpy(cv2.cvtColor(cv2.imread(cases[ids[0]]["image_path"]), cv2.COLOR_BGR2RGB)).cuda()
for _ in range(3):
    fp(crops(w0, [(0, 0, 224, 224)] * 41), yesno("red")); fp_full(w0[None], yesno("red"))
fo = (OUT / "rows.jsonl").open("w"); HUE = {"red": [(0, 8), (170, 179)], "purple": [(138, 165)], "blue": [(108, 130)]}
for i in ids:
    c = cases[i]; bgr = cv2.imread(c["image_path"])
    frame = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
    rec = dict(id=i, color=c["color"], present=c["present"], split=c["split"], gt=hsv.get(i), res=RES)
    localize(frame, c["color"], rec)
    if "W2" in rec:
        W2 = rec["W2"]; h = cv2.cvtColor(bgr[W2[1]:W2[3], W2[0]:W2[2]], cv2.COLOR_BGR2HSV)
        rec["other_px"] = {o: int(sum((cv2.inRange(h, (lo, 110, 40), (hi, 255, 255)) > 0).sum() for lo, hi in HUE[o])) for o in CN if o != c["color"]}
    fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
    print(i, round(rec.get("t_total", 0), 3), flush=True)
print("done", flush=True)
(OUT / "DONE").write_text("ok")
