#!/usr/bin/env python3
"""P11 replay variants for the presence-sweep tracker.

Usage is identical to p10, with an optional final variant name: base, A1, A2,
A3, or A4.  Each variant changes exactly one Stage-A rule so the nine-window
comparison remains paired with the p10 224/224 baseline.
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
RC, RF = [int(x) for x in sys.argv[2].split(",")]; RUNS = sys.argv[3].split(",")
TH = json.loads(Path(sys.argv[4]).read_text())["thresholds"] if len(sys.argv) > 4 else (0.4, 0.5, 0.5, 0.4)
VARIANT = sys.argv[5].upper() if len(sys.argv) > 5 else "BASE"
if VARIANT not in {"BASE", "A1", "A2", "A3", "A4"}:
    raise SystemExit(f"unknown variant {VARIANT}")
if VARIANT == "A4":
    TH = (0.5, 0.5, 0.4, 0.4)
T_WATCH, VERIFY_S, REFRESH_S, N1, N2, GRAY = 0.5, 0.5, 2.0, 8, 10, 128
VERIFY_S = 0.25 if VARIANT == "A1" else VERIFY_S
REFRESH_S = 1.0 if VARIANT == "A3" else REFRESH_S
VERIFY_SCALE = 1.2 if VARIANT == "A1" else 1.6
VERIFY_MIN = 40 if VARIANT == "A1" else 48
HUE = {"red": [(0, 8), (170, 179)], "purple": [(138, 165)], "blue": [(108, 130)]}

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fpc = FastPresence(model, tok, proc, res=RC); fpf = FastPresence(model, tok, proc, res=RF); fp_full = FastPresence(model, tok, proc, res=448)
fp = fpc

def yesno(c):
    return f"这张图片里有没有{CN[c]}的气球？只回答“是”或“否”。"

def timed(f, *a):
    torch.cuda.synchronize(); t = time.perf_counter(); r = f(*a); torch.cuda.synchronize(); return r, time.perf_counter() - t

def square(cx, cy, side, w=640, h=480):
    s = int(min(max(side, 32), h)); a = int(round(min(max(cx - s / 2, 0), w - s))); b = int(round(min(max(cy - s / 2, 0), h - s)))
    return a, b, a + s, b + s

def crops(frame, wins, RES=None):
    RES = RES or RC
    return torch.stack([torch.nn.functional.interpolate(frame[w[1]:w[3], w[0]:w[2]].permute(2, 0, 1)[None].float(), size=(RES, RES), mode="bilinear", align_corners=False)[0].permute(1, 2, 0).round().clamp(0, 255).byte() for w in wins])

def sweep_imgs(frame, W, n, RES=None):
    RES = RES or RC; c = crops(frame, [W], RES)[0]; S = W[2] - W[0]; pos = list(np.linspace(0, S, n + 2)[1:-1]); out = [c]
    for d in "LRTB":
        for q in pos:
            m = c.clone(); q = int(round(q * RES / S))
            if d == "L": m[:, :q] = GRAY
            if d == "R": m[:, RES - q:] = GRAY
            if d == "T": m[:q, :] = GRAY
            if d == "B": m[RES - q:, :] = GRAY
            out.append(m)
    return torch.stack(out), pos

def edges(ps, pos, W, th):
    S = W[2] - W[0]; n = len(pos); p0 = ps[0]; c = []
    for k in range(4):
        prof = [p0] + ps[1 + k * n:1 + (k + 1) * n]; xs = [0.0] + pos; t = th[k] * p0; v = float(S)
        for j in range(1, len(prof)):
            if prof[j - 1] >= t > prof[j]:
                a = (prof[j - 1] - t) / (prof[j - 1] - prof[j] + 1e-9); v = xs[j - 1] + a * (xs[j] - xs[j - 1]); break
        c.append(v)
    cL, cR, cT, cB = c; b = [W[0] + S - cR, W[1] + S - cB, W[0] + cL, W[1] + cT]
    return b if p0 >= 0.5 and b[2] > b[0] + 2 and b[3] > b[1] + 2 else None

def fine(frame, text, W):
    imgs, pos = sweep_imgs(frame, W, N2, RF); ps = fpf(imgs, text); return edges(ps, pos, W, TH)

def localize(frame, text):
    TW = 224; xs = np.linspace(0, 640 - TW, 5).astype(int); ys = np.linspace(0, 480 - TW, 3).astype(int)
    wins = [(int(x), int(y), int(x) + TW, int(y) + TW) for y in ys for x in xs]
    pt = fp(crops(frame, wins), text); on = [w for w, p in zip(wins, pt) if p >= .5]
    if not on: return None
    best = wins[int(np.argmax(pt))]; grp = [w for w in on if min(w[2], best[2]) > max(w[0], best[0]) and min(w[3], best[3]) > max(w[1], best[1])]
    roi = (max(w[0] for w in grp), max(w[1] for w in grp), min(w[2] for w in grp), min(w[3] for w in grp))
    if roi[2] - roi[0] < 48 or roi[3] - roi[1] < 48: roi = best
    e = None
    for W1 in (square((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2, max(roi[2] - roi[0], roi[3] - roi[1], 128)), tuple(best)):
        imgs, pos = sweep_imgs(frame, W1, N1); ps = fp(imgs, text); e = edges(ps, pos, W1, (.5,) * 4)
        if e: break
    if not e: return None
    side = max(64, 2.5 * max(e[2] - e[0], e[3] - e[1], 16)); return fine(frame, text, square((e[0] + e[2]) / 2, (e[1] + e[3]) / 2, side))

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0

def ce(a, b): return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)

_w = torch.zeros(480, 640, 3, dtype=torch.uint8, device="cuda")
for _ in range(3):
    fpc(crops(_w, [(0, 0, 224, 224)] * 41), yesno("red")); fpf(crops(_w, [(0, 0, 224, 224)] * 41, RF), yesno("red")); fp_full(_w[None], yesno("red"))

ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026"); summary = {}
for run in RUNS:
    d = ROOT / run / "audit"; color = run.split("_")[2]; ev = [json.loads(l) for l in open(d / "events.jsonl")]
    a = [e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", "")][0]
    fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
    yolo = [e for e in ev if e["event"] == "objects" and e.get("topic") == "yolo"]; stamps = [e["header_stamp"] - fr[0]["header_stamp"] for e in fr]; bgrs = [cv2.imread(str(d / e["file"])) for e in fr]
    def yolo_box(e):
        m = [y for y in yolo if abs(y["stamp"] - e["header_stamp"]) < 0.06]
        if not m: return "nodata"
        o = [x for x in min(m, key=lambda y: abs(y["stamp"] - e["header_stamp"]))["objects"] if x["name"] == color + "_balloon"]
        return o[0]["bbox"] if o else None
    text = yesno(color); gts = [yolo_box(e) for e in fr]; worker_free = 0.0; job = None; state = "SEARCH"; tracker = None; last_verify = last_refresh = -1e9; fails = 0; track_init = None; scan_size = None
    rows = []; calls = []
    for k, (ts, bgr) in enumerate(zip(stamps, bgrs)):
        if job and job["done"] <= ts:
            kind, box, src = job["kind"], job["box"], job["src"]; job = None
            if kind in ("loc", "refresh"):
                if box:
                    tracker = cv2.TrackerCSRT_create(); x1, y1, x2, y2 = [int(round(v)) for v in box]; iw, ih = max(4, x2 - x1), max(4, y2 - y1)
                    tracker.init(bgrs[src], (x1, y1, iw, ih)); track_init = (float(iw), float(ih)); scan_size = (float(iw), float(ih))
                    for j in range(src + 1, k):
                        ok, xywh = tracker.update(bgrs[j])
                        if not ok: break
                    state = "TRACK" if ok or k == src else "SEARCH"; fails = 0; last_refresh = stamps[src]
                elif kind == "refresh": fails += 1
            elif kind == "verify":
                if VARIANT == "A1" and not box:
                    state, tracker, track_init, scan_size = "SEARCH", None, None, None; fails = 0
                else: fails = 0 if box else fails + 1
            if fails >= 2: state, tracker, track_init, scan_size = "SEARCH", None, None, None
        pub = None
        if state == "TRACK" and tracker is not None:
            ok, xywh = tracker.update(bgr)
            if ok and xywh[2] > 2 and xywh[3] > 2:
                cx, cy = xywh[0] + xywh[2] / 2, xywh[1] + xywh[3] / 2
                if VARIANT == "A2" and scan_size and track_init:
                    s = math.sqrt((xywh[2] / track_init[0]) * (xywh[3] / track_init[1])); s = min(1.6, max(0.85, s)); ww, hh = scan_size[0] * s, scan_size[1] * s; pub = [max(0, cx - ww / 2), max(0, cy - hh / 2), min(640, cx + ww / 2), min(480, cy + hh / 2)]
                else: pub = [max(0, xywh[0]), max(0, xywh[1]), min(640, xywh[0] + xywh[2]), min(480, xywh[1] + xywh[3])]
            else: state, tracker, track_init, scan_size = "SEARCH", None, None, None
        if job is None and worker_free <= ts:
            frame = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
            if state == "SEARCH":
                p, dt = timed(lambda: fp_full(frame[None], text)[0]); calls.append(("watch", dt)); box, dt2 = (timed(localize, frame, text) if p >= T_WATCH else (None, 0.0))
                if p >= T_WATCH: calls.append(("localize", dt2)); job = dict(kind="loc", box=box, src=k, done=ts + dt + dt2)
                worker_free = ts + dt + dt2
            elif pub and ts - last_refresh >= REFRESH_S:
                cx, cy = (pub[0] + pub[2]) / 2, (pub[1] + pub[3]) / 2; W = square(cx, cy, max(64, 2.5 * max(pub[2] - pub[0], pub[3] - pub[1]))); box, dt = timed(fine, frame, text, W); calls.append(("refresh", dt)); job = dict(kind="refresh", box=box, src=k, done=ts + dt); worker_free = ts + dt; last_refresh = ts
            elif pub and ts - last_verify >= VERIFY_S:
                cx, cy = (pub[0] + pub[2]) / 2, (pub[1] + pub[3]) / 2; W = square(cx, cy, max(VERIFY_MIN, VERIFY_SCALE * max(pub[2] - pub[0], pub[3] - pub[1]))); p, dt = timed(lambda: fp(crops(frame, [W]), text)[0]); calls.append(("verify", dt)); job = dict(kind="verify", box=p >= .5, src=k, done=ts + dt); worker_free = ts + dt; last_verify = ts
        g = gts[k]; gg = g if isinstance(g, list) else None
        rows.append(dict(k=k, t=ts, gt=g, pub=pub, state=state, iou=iou(pub, gg) if pub and gg else None, ce=ce(pub, gg) if pub and gg else None, cin=bool(pub and gg and gg[0] <= (pub[0] + pub[2]) / 2 <= gg[2] and gg[1] <= (pub[1] + pub[3]) / 2 <= gg[3])))
    (OUT / f"{run}.json").write_text(json.dumps(dict(variant=VARIANT, rows=rows, calls=calls)))
    vis = [r for r in rows if r["gt"] and r["gt"] != "nodata"]; absent = [r for r in rows if r["gt"] is None]; pubv = [r for r in vis if r["pub"]]
    summary[run] = dict(frames=len(rows), visible=len(vis), published_when_visible=len(pubv), center_inside=sum(r["cin"] for r in vis), iou50=sum((r["iou"] or 0) >= .5 for r in vis), ce_med=statistics.median([r["ce"] for r in pubv]) if pubv else None, published_when_absent=sum(bool(r["pub"]) for r in absent), absent=len(absent), calls={k: (len([c for c in calls if c[0] == k]), round(statistics.median([c[1] for c in calls if c[0] == k]), 3)) for k in ("watch", "localize", "refresh", "verify") if any(c[0] == k for c in calls)})
    print(VARIANT, run, summary[run], flush=True)
(OUT / "summary.json").write_text(json.dumps(dict(variant=VARIANT, thresholds=TH, summary=summary), indent=1)); (OUT / "DONE").write_text("ok")
