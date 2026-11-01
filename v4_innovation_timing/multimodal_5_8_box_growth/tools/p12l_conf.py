#!/usr/bin/env python3
"""P12 (model-native tracking): FM9G local sweep every cycle; CSRT only interpolates between model results.
Derived from P9/P10: offline time-faithful replay of the proposed FM9G perception loop on real consecutive sensor1 frames.

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
RC, RF = [int(x) for x in sys.argv[2].split(",")]; RUNS = sys.argv[3].split(","); COLORS = None
TH = json.loads(Path(sys.argv[4]).read_text())["thresholds"] if len(sys.argv) > 4 else (0.4, 0.5, 0.5, 0.4)
T_WATCH, VERIFY_S, REFRESH_S, N1, N2, GRAY = 0.5, 0.5, 2.0, 8, 10, 128
NT = int(sys.argv[5]) if len(sys.argv) > 5 else 7
WF = float(sys.argv[6]) if len(sys.argv) > 6 else 2.2
HOLD = float(sys.argv[7]) if len(sys.argv) > 7 else 0.8
CONF = float(sys.argv[10]) if len(sys.argv) > 10 else 0.5
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
    return torch.stack([torch.nn.functional.interpolate(frame[w[1]:w[3], w[0]:w[2]].permute(2, 0, 1)[None].float(), size=(RES, RES),
                        mode="bilinear", align_corners=False)[0].permute(1, 2, 0).round().clamp(0, 255).byte() for w in wins])


def sweep_imgs(frame, W, n, RES=None):
    RES = RES or RC
    c = crops(frame, [W], RES)[0]; S = W[2] - W[0]; pos = list(np.linspace(0, S, n + 2)[1:-1]); out = [c]
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
    imgs, pos = sweep_imgs(frame, W, N2, RF); ps = fpf(imgs, text); return edges(ps, pos, W, TH)


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
    return e


def _edges(ps, pos, p0):
    n = len(pos); xs = [0.0] + pos; c = []
    for k in range(4):
        prof = [p0] + ps[1 + k * n:1 + (k + 1) * n]; t = TH[k] * p0; v = None
        for j in range(1, len(prof)):
            if prof[j - 1] >= t > prof[j]:
                a = (prof[j - 1] - t) / (prof[j - 1] - prof[j] + 1e-9); v = xs[j - 1] + a * (xs[j] - xs[j - 1]); break
        c.append(v)
    return c


def track_sweep(frame, text, box):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    side = max(56, WF * max(box[2] - box[0], box[3] - box[1]))
    W = square(cx, cy, side)
    imgs, pos = sweep_imgs(frame, W, NT, RF); ps = fpf(imgs, text)
    S = W[2] - W[0]; p0 = ps[0]
    if p0 < 0.5:
        return None
    c = _edges(ps, pos, p0)
    retried = False
    if sum(e is None for e in c) >= 2 and side < 400:
        side2 = min(400, 2.0 * side); W2 = square(cx, cy, side2)
        imgs2, pos2 = sweep_imgs(frame, W2, NT, RF); ps2 = fpf(imgs2, text); p0b = ps2[0]
        if p0b >= CONF:
            W, c, p0, S = W2, _edges(ps2, pos2, p0b), p0b, side2; retried = True
    cL, cR, cT, cB = c
    trust = retried and sum(e is None for e in c) >= 2
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
    fpc(crops(_w, [(0, 0, 224, 224)] * 41), yesno("red")); fpf(crops(_w, [(0, 0, 224, 224)] * 41, RF), yesno("red")); fp_full(_w[None], yesno("red"))

summary = {}
ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026")
for run in RUNS:
    d = ROOT / run / "audit"; color = run.split("_")[2]
    ev = [json.loads(l) for l in open(d / "events.jsonl")]
    a = [e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", "")][0]
    fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
    yolo = [e for e in ev if e["event"] == "objects" and e.get("topic") == "yolo"]
    stamps = [e["header_stamp"] - fr[0]["header_stamp"] for e in fr]
    bgrs = [cv2.imread(str(d / e["file"])) for e in fr]
    def yolo_box(e):
        m = [y for y in yolo if abs(y["stamp"] - e["header_stamp"]) < 0.06]
        if not m:
            return "nodata"
        o = [x for x in min(m, key=lambda y: abs(y["stamp"] - e["header_stamp"]))["objects"] if x["name"] == color + "_balloon"]
        return o[0]["bbox"] if o else None
    for color in [color]:
        text = yesno(color); gts = [yolo_box(e) for e in fr]
        worker_free = 0.0; job = None; state = "SEARCH"; tracker = None; last_model = -1e9; model_box = None; misses = 0; track_box = None
        rows = []; calls = []
        for k, (ts, bgr) in enumerate(zip(stamps, bgrs)):
            if job and job["done"] <= ts:
                box, src, job_kind = job["box"], job["src"], job["kind"]; job = None
                if box:
                    tracker = cv2.TrackerCSRT_create(); x1, y1, x2, y2 = [int(round(v)) for v in box]
                    tracker.init(bgrs[src], (x1, y1, max(4, x2 - x1), max(4, y2 - y1))); tbox = list(box); okk = True
                    for j in range(src + 1, k):
                        okk, xywh = tracker.update(bgrs[j])
                        if not okk:
                            break
                    state = "TRACK" if okk else "SEARCH"; last_model = stamps[src]; model_box = list(box)
                    if not okk:
                        tracker = None
                elif job_kind == "track" and misses == 0 and tracker is not None:
                    misses = 1          # one negative sweep: keep interpolating, re-check next cycle
                else:
                    state, tracker, model_box = "SEARCH", None, None
                if box:
                    misses = 0
            pub = None; track_box = None
            if state == "TRACK" and tracker is not None:
                ok, xywh = tracker.update(bgr)
                if ok and xywh[2] > 2 and xywh[3] > 2 and ts - last_model <= HOLD:
                    pub = [max(0, xywh[0]), max(0, xywh[1]), min(640, xywh[0] + xywh[2]), min(480, xywh[1] + xywh[3])]
                    track_box = pub
                    if misses:      # suspended after a negative sweep: keep the track for re-check, publish nothing
                        pub = None
                else:
                    state, tracker = "SEARCH", None
            if job is None and worker_free <= ts:
                frame = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
                if state == "TRACK" and tracker is not None and track_box:
                    box, dt = timed(track_sweep, frame, text, track_box); calls.append(("track", dt)); kind = "track"
                else:
                    box, dt = timed(localize, frame, text); calls.append(("acquire", dt)); kind = "acquire"
                job = dict(box=box, src=k, done=ts + dt, kind=kind); worker_free = ts + dt
            g = gts[k]
            gg = g if isinstance(g, list) else None
            rows.append(dict(k=k, t=ts, gt=g, pub=pub, state=state,
                             iou=iou(pub, gg) if pub and gg else None, ce=ce(pub, gg) if pub and gg else None,
                             cin=bool(pub and gg and gg[0] <= (pub[0] + pub[2]) / 2 <= gg[2] and gg[1] <= (pub[1] + pub[3]) / 2 <= gg[3])))
        (OUT / f"{run}.json").write_text(json.dumps(dict(rows=rows, calls=calls)))
        vis = [r for r in rows if r["gt"] and r["gt"] != "nodata"]
        absent = [r for r in rows if r["gt"] is None]
        pubv = [r for r in vis if r["pub"]]
        # acquisition latency: from first frame of each visible segment to first correct publish
        summary[run] = dict(
            frames=len(rows), visible=len(vis), published_when_visible=len(pubv),
            center_inside=sum(r["cin"] for r in vis), iou50=sum((r["iou"] or 0) >= .5 for r in vis),
            ce_med=statistics.median([r["ce"] for r in pubv]) if pubv else None,
            published_when_absent=sum(bool(r["pub"]) for r in absent), absent=len(absent),
            calls={k: (len([c for c in calls if c[0] == k]), round(statistics.median([c[1] for c in calls if c[0] == k]), 3))
                   for k in ("acquire", "track") if any(c[0] == k for c in calls)})
        print(run, summary[run], flush=True)
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
(OUT / "DONE").write_text("ok")
