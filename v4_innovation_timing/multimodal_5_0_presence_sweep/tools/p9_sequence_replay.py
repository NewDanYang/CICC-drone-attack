#!/usr/bin/env python3
"""P9: offline time-faithful replay of the proposed FM9G perception loop on real consecutive sensor1 frames.

Virtual clock: frames arrive at their recorded source stamps. The model worker is single-threaded; each model call
advances the worker clock by its *measured* GPU latency, so results are only applied to frames that would really have
arrived after the call finished (CSRT replays the gap, exactly like runtime.py ReplayTracker). Published box at frame k
is compared with a label-only HSV box (never visible to the pipeline).

Loop per colour:
  SEARCH  : watch = full-frame presence on the newest frame; if p>=T_WATCH -> localize (tiles + 2-pass sweep) on that frame
  TRACK   : CSRT on every frame; every VERIFY_S: presence on the tracked crop (x1.6); fail twice -> drop to SEARCH
            every REFRESH_S: pass-2 sweep around the track -> re-init CSRT (fixes scale/centre drift)
usage: p9_sequence_replay.py OUT RES run8,run9,run10 [colors]
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
RES = int(sys.argv[2]); RUNS = sys.argv[3].split(","); COLORS = sys.argv[4].split(",") if len(sys.argv) > 4 else list(CN)
TH = json.loads(Path(sys.argv[5]).read_text())["thresholds"] if len(sys.argv) > 5 else (0.4, 0.5, 0.4, 0.4)
T_WATCH, VERIFY_S, REFRESH_S, N1, N2, GRAY = 0.5, 0.5, 2.0, 8, 10, 128
HUE = {"red": [(0, 8), (170, 179)], "purple": [(138, 165)], "blue": [(108, 130)]}

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fp = FastPresence(model, tok, proc, res=RES); fp_full = FastPresence(model, tok, proc, res=448)


def yesno(c):
    return f"这张图片里有没有{CN[c]}的气球？只回答“是”或“否”。"


def timed(f, *a):
    torch.cuda.synchronize(); t = time.perf_counter(); r = f(*a); torch.cuda.synchronize(); return r, time.perf_counter() - t


def square(cx, cy, side, w=640, h=480):
    s = int(min(max(side, 32), h)); a = int(round(min(max(cx - s / 2, 0), w - s))); b = int(round(min(max(cy - s / 2, 0), h - s)))
    return a, b, a + s, b + s


def crops(frame, wins):
    return torch.stack([torch.nn.functional.interpolate(frame[w[1]:w[3], w[0]:w[2]].permute(2, 0, 1)[None].float(), size=(RES, RES),
                        mode="bilinear", align_corners=False)[0].permute(1, 2, 0).round().clamp(0, 255).byte() for w in wins])


def sweep_imgs(frame, W, n):
    c = crops(frame, [W])[0]; S = W[2] - W[0]; pos = list(np.linspace(0, S, n + 2)[1:-1]); out = [c]
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
    cL, cR, cT, cB = c
    b = [W[0] + S - cR, W[1] + S - cB, W[0] + cL, W[1] + cT]
    return b if p0 >= 0.5 and b[2] > b[0] + 2 and b[3] > b[1] + 2 else None


def fine(frame, text, W):
    imgs, pos = sweep_imgs(frame, W, N2); ps = fp(imgs, text); return edges(ps, pos, W, TH)


def localize(frame, text):
    TW = 224; xs = np.linspace(0, 640 - TW, 5).astype(int); ys = np.linspace(0, 480 - TW, 3).astype(int)
    wins = [(int(x), int(y), int(x) + TW, int(y) + TW) for y in ys for x in xs]
    pt = fp(crops(frame, wins), text); on = [w for w, p in zip(wins, pt) if p >= .5]
    if not on:
        return None
    best = wins[int(np.argmax(pt))]
    grp = [w for w in on if min(w[2], best[2]) > max(w[0], best[0]) and min(w[3], best[3]) > max(w[1], best[1])]
    roi = (max(w[0] for w in grp), max(w[1] for w in grp), min(w[2] for w in grp), min(w[3] for w in grp))
    if roi[2] - roi[0] < 48 or roi[3] - roi[1] < 48:
        roi = best
    for W1 in (square((roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2, max(roi[2] - roi[0], roi[3] - roi[1], 128)), tuple(best)):
        imgs, pos = sweep_imgs(frame, W1, N1); ps = fp(imgs, text); e = edges(ps, pos, W1, (.5,) * 4)
        if e:
            break
    if not e:
        return None
    side = max(64, 2.5 * max(e[2] - e[0], e[3] - e[1], 16))
    return fine(frame, text, square((e[0] + e[2]) / 2, (e[1] + e[3]) / 2, side))


def hsv_box(bgr, color):
    h = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV); m = np.zeros(h.shape[:2], np.uint8)
    for lo, hi in HUE[color]:
        m |= cv2.inRange(h, (lo, 110, 40), (hi, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m, 8)
    c = [st[i] for i in range(1, n) if st[i, 4] >= 60 and 0.4 <= st[i, 3] / max(1, st[i, 2]) <= 2.5]
    if not c:
        return None
    s = max(c, key=lambda s: s[4]); return [int(s[0]), int(s[1]), int(s[0] + s[2]), int(s[1] + s[3])]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def ce(a, b):
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


# warmup
_w = torch.zeros(480, 640, 3, dtype=torch.uint8, device="cuda")
for _ in range(3):
    fp(crops(_w, [(0, 0, 224, 224)] * 41), yesno("red")); fp_full(_w[None], yesno("red"))

summary = {}
for run in RUNS:
    d = Path(f"/root/gpufree-data/mm36_data/{run}")
    ev = [json.loads(l) for l in open(d / "events.jsonl")]
    fr = [e for e in ev if e.get("event") == "frame" and (d / e["image"]).exists()]
    stamps = [e["source_stamp"]["secs"] + e["source_stamp"]["nsecs"] * 1e-9 for e in fr]
    t0 = stamps[0]; stamps = [s - t0 for s in stamps]
    bgrs = [cv2.imread(str(d / e["image"])) for e in fr]
    for color in COLORS:
        text = yesno(color); gts = [hsv_box(b, color) for b in bgrs]
        worker_free = 0.0; job = None; state = "SEARCH"; tracker = None; last_verify = last_refresh = -1e9; fails = 0
        rows = []; calls = []
        for k, (ts, bgr) in enumerate(zip(stamps, bgrs)):
            # 1. finish pending job whose result is available by now
            if job and job["done"] <= ts:
                kind, box, src = job["kind"], job["box"], job["src"]; job = None
                if kind in ("loc", "refresh"):
                    if box:
                        tracker = cv2.TrackerCSRT_create(); x1, y1, x2, y2 = [int(round(v)) for v in box]
                        tracker.init(bgrs[src], (x1, y1, max(4, x2 - x1), max(4, y2 - y1))); tbox = list(box)
                        for j in range(src + 1, k):   # replay frames that arrived during inference
                            ok, xywh = tracker.update(bgrs[j]); tbox = [xywh[0], xywh[1], xywh[0] + xywh[2], xywh[1] + xywh[3]] if ok else None
                            if not ok:
                                break
                        state = "TRACK" if tbox else "SEARCH"; fails = 0; last_refresh = stamps[src]
                    elif kind == "refresh":
                        fails += 1
                elif kind == "verify":
                    fails = 0 if box else fails + 1
                if fails >= 2:
                    state, tracker = "SEARCH", None
            # 2. CSRT on this frame
            pub = None
            if state == "TRACK" and tracker is not None:
                ok, xywh = tracker.update(bgr)
                if ok and xywh[2] > 2 and xywh[3] > 2:
                    pub = [max(0, xywh[0]), max(0, xywh[1]), min(640, xywh[0] + xywh[2]), min(480, xywh[1] + xywh[3])]
                else:
                    state, tracker = "SEARCH", None
            # 3. schedule a model job if worker idle
            if job is None and worker_free <= ts:
                frame = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
                if state == "SEARCH":
                    p, dt = timed(lambda: fp_full(frame[None], text)[0]); calls.append(("watch", dt))
                    box, dt2 = (timed(localize, frame, text) if p >= T_WATCH else (None, 0.0))
                    if p >= T_WATCH:
                        calls.append(("localize", dt2))
                        job = dict(kind="loc", box=box, src=k, done=ts + dt + dt2)
                    worker_free = ts + dt + dt2
                elif pub and ts - last_refresh >= REFRESH_S:
                    cx, cy = (pub[0] + pub[2]) / 2, (pub[1] + pub[3]) / 2
                    W = square(cx, cy, max(64, 2.5 * max(pub[2] - pub[0], pub[3] - pub[1])))
                    box, dt = timed(fine, frame, text, W); calls.append(("refresh", dt))
                    job = dict(kind="refresh", box=box, src=k, done=ts + dt); worker_free = ts + dt; last_refresh = ts
                elif pub and ts - last_verify >= VERIFY_S:
                    cx, cy = (pub[0] + pub[2]) / 2, (pub[1] + pub[3]) / 2
                    W = square(cx, cy, max(48, 1.6 * max(pub[2] - pub[0], pub[3] - pub[1])))
                    p, dt = timed(lambda: fp(crops(frame, [W]), text)[0]); calls.append(("verify", dt))
                    job = dict(kind="verify", box=p >= .5, src=k, done=ts + dt); worker_free = ts + dt; last_verify = ts
            g = gts[k]
            rows.append(dict(k=k, t=ts, gt=g, pub=pub, state=state,
                             iou=iou(pub, g) if pub and g else None, ce=ce(pub, g) if pub and g else None,
                             cin=bool(pub and g and g[0] <= (pub[0] + pub[2]) / 2 <= g[2] and g[1] <= (pub[1] + pub[3]) / 2 <= g[3])))
        (OUT / f"{run}_{color}.json").write_text(json.dumps(dict(rows=rows, calls=calls)))
        vis = [r for r in rows if r["gt"] and max(r["gt"][2] - r["gt"][0], r["gt"][3] - r["gt"][1]) >= 12]
        absent = [r for r in rows if not r["gt"]]
        pubv = [r for r in vis if r["pub"]]
        # acquisition latency: from first frame of each visible segment to first correct publish
        summary[f"{run}_{color}"] = dict(
            frames=len(rows), visible=len(vis), published_when_visible=len(pubv),
            center_inside=sum(r["cin"] for r in vis), iou50=sum((r["iou"] or 0) >= .5 for r in vis),
            ce_med=statistics.median([r["ce"] for r in pubv]) if pubv else None,
            published_when_absent=sum(bool(r["pub"]) for r in absent), absent=len(absent),
            calls={k: (len([c for c in calls if c[0] == k]), round(statistics.median([c[1] for c in calls if c[0] == k]), 3))
                   for k in ("watch", "localize", "refresh", "verify") if any(c[0] == k for c in calls)})
        print(run, color, summary[f"{run}_{color}"], flush=True)
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
(OUT / "DONE").write_text("ok")
