#!/usr/bin/env python3
"""P4 (offline, zero-shot base): localization derived from FM9G presence answers, not from coordinate regression.

Pipeline per frame (only image + requested color are given to the model; GT used only for scoring):
  1. full-frame presence P(是)                                     (1 forward)
  2. 15 overlapping 224px tiles presence -> ROI = union of tiles with p>=T   (1 batched forward)
  3. edge sweeps inside a square window around the ROI: mask (gray) everything left of x / right of x / above y /
     below y for N positions; P(是) profile per direction; crossing points -> box     (1 batched forward, 4N images)
  4. (comparison) zoom-native: batched <box> on K jittered crops around ROI, median box
GT = tight HSV boxes from P1. Reports gate (IoU>=.5 & center err<=max(8,0.2 diag)), center-inside, latency.
"""
import json, math, re, statistics, sys, time
from pathlib import Path
import cv2, numpy as np, torch
from PIL import Image
from transformers import AutoModel, AutoProcessor, AutoTokenizer

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=False)
NSWEEP = int(sys.argv[2]) if len(sys.argv) > 2 else 8
T_TILE = 0.5
BOX = re.compile(r"<box>\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*</box>")
GRAY = (128, 128, 128)


def yesno(c):
    return f"这张图片里有没有{CN[c]}的气球？只回答“是”或“否”。"


def native(c):
    return (f"请定位图片中实际可见的{CN[c]}气球球体，排除小车、绳子和墙面。只输出一个原生格式框：<box>x1 y1 x2 y2</box>。"
            "四个坐标按当前图片宽高归一化到0到1000，x向右增加、y向下增加；没有实际可见目标时输出<box>None</box>。不要解释，不要Markdown。")


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def cerr(a, b):
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


def gate(p, t):
    return iou(p, t) >= 0.5 and cerr(p, t) <= max(8, 0.2 * math.hypot(t[2] - t[0], t[3] - t[1]))


tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
YES, NO = tok.encode("是", add_special_tokens=False)[-1], tok.encode("否", add_special_tokens=False)[-1]


def pil(bgr, size=None):
    if size:
        bgr = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_CUBIC)
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def presence(imgs, text, slices=1):
    prompts = [proc.tokenizer.apply_chat_template([{"role": "user", "content": "(<image>./</image>)\n" + text}],
                                                  tokenize=False, add_generation_prompt=True) for _ in imgs]
    with torch.inference_mode():
        inp = proc(prompts, [[im] for im in imgs], max_slice_nums=slices, return_tensors="pt", max_length=8192).to(model.device)
        inp.pop("image_sizes")
        emb, _ = model.get_vllm_embedding(inp)
        am = inp["attention_mask"]; pos = (am.long().cumsum(-1) - 1).clamp(min=0)
        lg = model.llm(inputs_embeds=emb, attention_mask=am, position_ids=pos).logits[:, -1].float()
    return torch.softmax(torch.stack([lg[:, YES], lg[:, NO]], -1), -1)[:, 0].tolist()


def boxes_batched(imgs, text):
    with torch.inference_mode():
        ans = model.chat(image=None, msgs=[[{"role": "user", "content": [im, text]}] for im in imgs], tokenizer=tok,
                         processor=proc, sampling=False, num_beams=1, max_new_tokens=24, max_slice_nums=1)
    return ans


def square(x0, y0, x1, y1, min_side, w=640, h=480):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; s = int(min(max(x1 - x0, y1 - y0, min_side), h))
    a = int(round(min(max(cx - s / 2, 0), w - s))); b = int(round(min(max(cy - s / 2, 0), h - s)))
    return a, b, a + s, b + s


def crossing(ps, coords, rising):
    """first coordinate where P(yes) leaves the 'present' regime; linear interpolation at 0.5."""
    for k in range(1, len(ps)):
        if ps[k - 1] >= 0.5 > ps[k]:
            t = (ps[k - 1] - 0.5) / (ps[k - 1] - ps[k] + 1e-9)
            return coords[k - 1] + t * (coords[k] - coords[k - 1])
    return None


def localize(bgr, color, rec):
    t0 = time.perf_counter()
    pf = presence([pil(bgr)], yesno(color), slices=9)[0]; rec["p_full"] = pf
    TW = 224; xs = np.linspace(0, 640 - TW, 5).astype(int); ys = np.linspace(0, 480 - TW, 3).astype(int)
    wins = [(int(x), int(y), int(x) + TW, int(y) + TW) for y in ys for x in xs]
    pt = presence([pil(bgr[w[1]:w[3], w[0]:w[2]], 448) for w in wins], yesno(color)); rec["p_tiles"] = pt
    t1 = time.perf_counter()
    on = [w for w, p in zip(wins, pt) if p >= T_TILE]
    if not on:
        k = int(np.argmax(pt)); on = [wins[k]] if pt[k] >= 0.3 else []
    if not on:
        rec["t_coarse"] = t1 - t0; return None
    # ROI = intersection of positive tiles if non-empty (target lies in all of them), else best tile
    ix0 = max(w[0] for w in on); iy0 = max(w[1] for w in on); ix1 = min(w[2] for w in on); iy1 = min(w[3] for w in on)
    roi = (ix0, iy0, ix1, iy1) if ix1 - ix0 > 16 and iy1 - iy0 > 16 else on[int(np.argmax([pt[wins.index(w)] for w in on]))]
    rec["roi"] = roi
    W = square(*roi, min_side=160)  # analysis window
    rec["window"] = W
    crop = bgr[W[1]:W[3], W[0]:W[2]].copy(); S = crop.shape[0]
    pos = np.linspace(0, S, NSWEEP + 2)[1:-1]
    imgs = []
    for direction in ("L", "R", "T", "B"):
        for q in pos:
            m = crop.copy(); q = int(q)
            if direction == "L": m[:, :q] = GRAY       # remove left part -> crossing ~ balloon right side
            if direction == "R": m[:, S - q:] = GRAY   # remove right part -> crossing ~ balloon left side
            if direction == "T": m[:q, :] = GRAY
            if direction == "B": m[S - q:, :] = GRAY
            imgs.append(pil(m, 448))
    ps = presence(imgs, yesno(color)); rec["sweep"] = ps
    t2 = time.perf_counter()
    n = NSWEEP; L, R, T, B = ps[:n], ps[n:2 * n], ps[2 * n:3 * n], ps[3 * n:]
    cL = crossing(L, list(pos), True); cR = crossing(R, list(pos), True)
    cT = crossing(T, list(pos), True); cB = crossing(B, list(pos), True)
    rec.update(t_coarse=t1 - t0, t_sweep=t2 - t1)
    if None in (cL, cR, cT, cB):
        return None
    # masking from left passes balloon at x=cL (local); from right at S-cR. Balloon spans roughly [S-cR, cL].
    x0, x1 = W[0] + min(S - cR, cL), W[0] + max(S - cR, cL)
    y0, y1 = W[1] + min(S - cB, cT), W[1] + max(S - cB, cT)
    return [x0, y0, x1, y1]


def zoom_native(bgr, color, W, K=6, rng=np.random.default_rng(0)):
    t = time.perf_counter(); S = W[2] - W[0]; imgs, wins = [], []
    for k in range(K):
        d = rng.uniform(-0.12, 0.12, 2) * S if k else np.zeros(2); s = int(S * (rng.uniform(0.85, 1.15) if k else 1))
        w = square(W[0] + d[0], W[1] + d[1], W[0] + d[0] + s, W[1] + d[1] + s, min_side=s)
        wins.append(w); imgs.append(pil(bgr[w[1]:w[3], w[0]:w[2]], 448))
    ans = boxes_batched(imgs, native(color)); bx = []
    for a, w in zip(ans, wins):
        m = BOX.search(a)
        if m:
            v = [int(x) for x in m.groups()]; s = w[2] - w[0]
            bx.append([w[0] + v[0] * s / 1000, w[1] + v[1] * s / 1000, w[0] + v[2] * s / 1000, w[1] + v[3] * s / 1000])
    lat = time.perf_counter() - t
    return ([float(np.median([b[i] for b in bx])) for i in range(4)] if bx else None), (bx[0] if ans and BOX.search(ans[0]) and bx else None), lat, ans


cases = {c["id"]: c for d in ("mm40_spatial_clean", "mm41_run8_mix")
         for c in json.loads(Path(f"/root/gpufree-data/{d}/data/cases.json").read_text())}
hsv = {}
for f in ("p1_mm40.json", "p1_mm41.json"):
    for r in json.loads(Path(f"/root/gpufree-data/fm_research/{f}").read_text()):
        if r.get("hsv") and r["iou"] >= 0.3:
            hsv[r["id"]] = r["hsv"]
ids = [i for i, c in cases.items() if c["split"] in ("test", "validation") and (not c["present"] or i in hsv)]
# warmup
_ = presence([pil(cv2.imread(cases[ids[0]]["image_path"]))], yesno("red"))
rows = []; fo = (OUT / "rows.jsonl").open("w")
for i in ids:
    c = cases[i]; bgr = cv2.imread(c["image_path"]); gt = hsv.get(i)
    rec = dict(id=i, color=c["color"], present=c["present"])
    box = localize(bgr, c["color"], rec); rec["sweep_box"] = box
    if "window" in rec:
        zb, z1, zl, za = zoom_native(bgr, c["color"], rec["window"]); rec.update(zoom_med=zb, zoom_single=z1, t_zoom=zl, zoom_answers=za)
    if gt:
        rec["gt"] = gt; rec["gt_max"] = max(gt[2] - gt[0], gt[3] - gt[1])
        for k in ("sweep_box", "zoom_med", "zoom_single"):
            b = rec.get(k)
            if b:
                rec[k + "_eval"] = dict(iou=iou(b, gt), cerr=cerr(b, gt), gate=bool(gate(b, gt)),
                                        cin=bool(gt[0] <= (b[0] + b[2]) / 2 <= gt[2] and gt[1] <= (b[1] + b[3]) / 2 <= gt[3]))
        if "roi" in rec:
            r_ = rec["roi"]; gc = ((gt[0] + gt[2]) / 2, (gt[1] + gt[3]) / 2)
            rec["roi_contains_gt_center"] = bool(r_[0] <= gc[0] <= r_[2] and r_[1] <= gc[1] <= r_[3])
    rows.append(rec); fo.write(json.dumps(rec, ensure_ascii=False) + "\n"); fo.flush()
    print(i, {k: rec.get(k + "_eval", {}).get("gate") for k in ("sweep_box", "zoom_med")}, flush=True)

P = [r for r in rows if r["present"]]; N = [r for r in rows if not r["present"]]
S = dict(n_pos=len(P), n_neg=len(N),
         full_presence_pos=f"{sum(r['p_full'] >= .5 for r in P)}/{len(P)}", full_presence_neg=f"{sum(r['p_full'] >= .5 for r in N)}/{len(N)}",
         roi_found_pos=f"{sum('roi' in r for r in P)}/{len(P)}", roi_found_neg=f"{sum('roi' in r for r in N)}/{len(N)}",
         roi_contains_gt=f"{sum(r.get('roi_contains_gt_center', False) for r in P)}/{len(P)}",
         t_coarse_med=statistics.median([r["t_coarse"] for r in rows]),
         t_sweep_med=statistics.median([r["t_sweep"] for r in rows if "t_sweep" in r]) if any("t_sweep" in r for r in rows) else None,
         t_zoom_med=statistics.median([r["t_zoom"] for r in rows if "t_zoom" in r]) if any("t_zoom" in r for r in rows) else None)
for k in ("sweep_box", "zoom_med", "zoom_single"):
    ev = [r[k + "_eval"] for r in P if k + "_eval" in r]
    S[k] = dict(produced=f"{len(ev)}/{len(P)}", gate=f"{sum(e['gate'] for e in ev)}/{len(P)}", cin=f"{sum(e['cin'] for e in ev)}/{len(P)}",
                cerr_med=statistics.median([e["cerr"] for e in ev]) if ev else None, iou_med=statistics.median([e["iou"] for e in ev]) if ev else None,
                by_color={col: f"{sum(r.get(k + '_eval', {}).get('gate', False) for r in P if r['color'] == col)}/{sum(r['color'] == col for r in P)}" for col in CN},
                small_lt40=f"{sum(r.get(k + '_eval', {}).get('gate', False) for r in P if r['gt_max'] < 40)}/{sum(r['gt_max'] < 40 for r in P)}")
(OUT / "summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1))
print(json.dumps(S, ensure_ascii=False, indent=1))
