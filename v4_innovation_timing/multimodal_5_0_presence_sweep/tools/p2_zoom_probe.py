#!/usr/bin/env python3
"""P2: does FM9G4B-V localize precisely when the balloon is zoomed (stage-2 of a coarse-to-fine cascade)?

Offline only. Ground truth = tight HSV boxes from P1 (label-only). Crop windows are centered at GT center plus a
random offset, emulating an imperfect stage-1; the model never sees GT. Negatives: same-size crops with no target color.
"""
import json, math, random, re, statistics, sys, time
from pathlib import Path
import cv2, numpy as np, torch
from PIL import Image
from transformers import AutoModel, AutoProcessor, AutoTokenizer

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
PROMPTS = {
    "native": lambda c: (f"请定位图片中实际可见的{CN[c]}气球球体，排除小车、绳子和墙面。只输出一个原生格式框：<box>x1 y1 x2 y2</box>。"
                         "四个坐标按当前图片宽高归一化到0到1000，x向右增加、y向下增加；没有实际可见目标时输出<box>None</box>。不要解释，不要Markdown。"),
    "ref": lambda c: f"请检测图中的<ref>{CN[c]}气球</ref>，输出它的边界框。",
}
BOX = re.compile(r"<box>\s*\(?\s*(\d+)[\s,]+(\d+)\s*\)?[\s,]*\(?\s*(\d+)[\s,]+(\d+)\s*\)?\s*</box>")
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=False)
SIDES = [int(s) for s in sys.argv[2].split(",")] if len(sys.argv) > 2 else [96, 160, 240]
PROMPT_KEYS = sys.argv[3].split(",") if len(sys.argv) > 3 else ["native"]
RES = 448
random.seed(7)


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def cerr(a, b):
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


def gate(p, t):
    return iou(p, t) >= 0.5 and cerr(p, t) <= max(8, 0.2 * math.hypot(t[2] - t[0], t[3] - t[1]))


def crop_window(cx, cy, side, w=640, h=480):
    x0 = int(round(min(max(cx - side / 2, 0), w - side))); y0 = int(round(min(max(cy - side / 2, 0), h - side)))
    return x0, y0, x0 + side, y0 + side


tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()


def ask(img, text):
    t = time.perf_counter()
    with torch.inference_mode():
        a = model.chat(image=None, msgs=[{"role": "user", "content": [img, text]}], tokenizer=tok, processor=proc,
                       sampling=False, num_beams=1, max_new_tokens=48)
    return a, time.perf_counter() - t


cases = {c["id"]: c for c in json.loads(Path("/root/gpufree-data/mm40_spatial_clean/data/cases.json").read_text())}
hsv = [r for r in json.loads(Path("/root/gpufree-data/fm_research/p1_mm40.json").read_text()) if r.get("hsv")]
# keep rows whose HSV box agrees with the reviewed label at least loosely (reject obvious mask mismatches)
hsv = [r for r in hsv if r["iou"] >= 0.3]
rows, f = [], (OUT / "rows.jsonl").open("w")
for r in hsv:
    c = cases[r["id"]]; im = cv2.imread(c["image_path"]); gt = r["hsv"]
    gw, gh = gt[2] - gt[0], gt[3] - gt[1]
    for side in SIDES:
        if max(gw, gh) > side * 0.9:
            continue
        off = side * 0.25
        cx = (gt[0] + gt[2]) / 2 + random.uniform(-off, off); cy = (gt[1] + gt[3]) / 2 + random.uniform(-off, off)
        x0, y0, x1, y1 = crop_window(cx, cy, side)
        crop = cv2.resize(im[y0:y1, x0:x1], (RES, RES), interpolation=cv2.INTER_CUBIC)
        pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        gt_c = [max(gt[0], x0) - x0, max(gt[1], y0) - y0, min(gt[2], x1) - x0, min(gt[3], y1) - y0]
        for pk in PROMPT_KEYS:
            ans, lat = ask(pil, PROMPTS[pk](r["color"]))
            m = BOX.search(ans)
            row = dict(id=r["id"], split=r["split"], color=r["color"], side=side, prompt=pk, window=[x0, y0, x1, y1],
                       gt=gt, gt_max_side=max(gw, gh), answer=ans, latency=lat, parsed=bool(m))
            if m:
                v = [int(x) for x in m.groups()]
                p = [x0 + v[0] * side / 1000, y0 + v[1] * side / 1000, x0 + v[2] * side / 1000, y0 + v[3] * side / 1000]
                row.update(pred=p, iou=iou(p, gt), cerr=cerr(p, gt), gate=gate(p, gt),
                           center_inside=gt[0] <= (p[0] + p[2]) / 2 <= gt[2] and gt[1] <= (p[1] + p[3]) / 2 <= gt[3])
            rows.append(row); f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
    print(len(rows), r["id"], flush=True)

# negatives: crops from sky / wall frames (present=False cases) and crops of a different-color balloon
negs = [c for c in cases.values() if not c["present"]][:24]
nrows = []
for c in negs:
    im = cv2.imread(c["image_path"])
    for side in SIDES[:2]:
        x0, y0, x1, y1 = crop_window(random.uniform(0, 640), random.uniform(0, 480), side)
        pil = Image.fromarray(cv2.cvtColor(cv2.resize(im[y0:y1, x0:x1], (RES, RES)), cv2.COLOR_BGR2RGB))
        for pk in PROMPT_KEYS:
            ans, lat = ask(pil, PROMPTS[pk](c["color"]))
            nrows.append(dict(id=c["id"], side=side, prompt=pk, answer=ans, false_box=bool(BOX.search(ans))))
cross = []  # wrong-color query on a crop centred on another balloon
for r in hsv[::3]:
    other = {"red": "blue", "purple": "red", "blue": "purple"}[r["color"]]
    c = cases[r["id"]]; im = cv2.imread(c["image_path"]); gt = r["hsv"]
    x0, y0, x1, y1 = crop_window((gt[0] + gt[2]) / 2, (gt[1] + gt[3]) / 2, SIDES[0] if max(gt[2]-gt[0], gt[3]-gt[1]) < SIDES[0]*.9 else SIDES[-1])
    pil = Image.fromarray(cv2.cvtColor(cv2.resize(im[y0:y1, x0:x1], (RES, RES)), cv2.COLOR_BGR2RGB))
    for pk in PROMPT_KEYS:
        ans, _ = ask(pil, PROMPTS[pk](other))
        cross.append(dict(id=r["id"], asked=other, prompt=pk, answer=ans, false_box=bool(BOX.search(ans))))
(OUT / "negatives.json").write_text(json.dumps(dict(empty=nrows, cross_color=cross), ensure_ascii=False, indent=1))

summary = {}
for pk in PROMPT_KEYS:
    for side in SIDES:
        rs = [r for r in rows if r["side"] == side and r["prompt"] == pk]
        if not rs:
            continue
        ok = [r for r in rs if r.get("pred")]
        key = f"{pk}_s{side}"
        summary[key] = dict(n=len(rs), parsed=len(ok), gate=sum(r["gate"] for r in ok),
                            center_inside=sum(r["center_inside"] for r in ok),
                            median_cerr=statistics.median([r["cerr"] for r in ok]) if ok else None,
                            median_iou=statistics.median([r["iou"] for r in ok]) if ok else None,
                            by_color={col: f"{sum(r.get('gate', False) for r in rs if r['color']==col)}/{sum(r['color']==col for r in rs)}" for col in CN},
                            small_lt40=f"{sum(r.get('gate', False) for r in rs if r['gt_max_side']<40)}/{sum(r['gt_max_side']<40 for r in rs)}",
                            median_latency=statistics.median([r["latency"] for r in rs]))
    summary[f"{pk}_neg_empty_false_box"] = f"{sum(r['false_box'] for r in nrows if r['prompt']==pk)}/{sum(r['prompt']==pk for r in nrows)}"
    summary[f"{pk}_neg_cross_false_box"] = f"{sum(r['false_box'] for r in cross if r['prompt']==pk)}/{sum(r['prompt']==pk for r in cross)}"
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
print(json.dumps(summary, ensure_ascii=False, indent=1))
