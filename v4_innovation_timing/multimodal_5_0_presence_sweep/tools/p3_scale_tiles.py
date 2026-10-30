#!/usr/bin/env python3
"""P3 (offline, zero-shot base model):
 A. full frame at input upscale 1x/2x/3x -> native <box>; does more slices (more visual tokens / pixel) sharpen boxes?
 B. batched tile presence scoring via first-token logits (是/否) -> heatmap; is the GT inside the top tile? latency?
GT = tight HSV boxes from P1 (label-only). Frames: run10 test + run8/run9 validation (never trained in base).
"""
import json, math, statistics, sys, time
from pathlib import Path
import cv2, numpy as np, torch
from PIL import Image
from transformers import AutoModel, AutoProcessor, AutoTokenizer

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=False)
import re
BOX = re.compile(r"<box>\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*</box>")


def native(c):
    return (f"请定位图片中实际可见的{CN[c]}气球球体，排除小车、绳子和墙面。只输出一个原生格式框：<box>x1 y1 x2 y2</box>。"
            "四个坐标按当前图片宽高归一化到0到1000，x向右增加、y向下增加；没有实际可见目标时输出<box>None</box>。不要解释，不要Markdown。")


def yesno(c):
    return f"这张图片里有没有{CN[c]}的气球？只回答“是”或“否”。"


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
YES = tok.encode("是", add_special_tokens=False); NO = tok.encode("否", add_special_tokens=False)
print("yes/no ids", YES, NO, flush=True)
YES, NO = YES[-1], NO[-1]


def chat(img, text, n=48):
    t = time.perf_counter()
    with torch.inference_mode():
        a = model.chat(image=None, msgs=[{"role": "user", "content": [img, text]}], tokenizer=tok, processor=proc,
                       sampling=False, num_beams=1, max_new_tokens=n)
    return a, time.perf_counter() - t


def presence_logits(imgs, text):
    """One batched forward; returns P(是) from the first answer token (renormalised over 是/否) and top token."""
    prompts = [proc.tokenizer.apply_chat_template([{"role": "user", "content": "(<image>./</image>)\n" + text}],
                                                  tokenize=False, add_generation_prompt=True) for _ in imgs]
    t = time.perf_counter()
    with torch.inference_mode():
        inp = proc(prompts, [[im] for im in imgs], max_slice_nums=1, return_tensors="pt", max_length=8192).to(model.device)
        inp.pop("image_sizes")
        emb, _ = model.get_vllm_embedding(inp)
        am = inp["attention_mask"]
        pos = (am.long().cumsum(-1) - 1).clamp(min=0)
        logits = model.llm(inputs_embeds=emb, attention_mask=am, position_ids=pos).logits[:, -1].float()
    lat = time.perf_counter() - t
    lp = torch.log_softmax(logits, -1)
    p = torch.softmax(torch.stack([lp[:, YES], lp[:, NO]], -1), -1)[:, 0].tolist()
    top = [tok.decode([i]) for i in logits.argmax(-1).tolist()]
    return p, top, lat


cases = {c["id"]: c for d in ("mm40_spatial_clean", "mm41_run8_mix")
         for c in json.loads(Path(f"/root/gpufree-data/{d}/data/cases.json").read_text())}
hsv = {}
for f in ("p1_mm40.json", "p1_mm41.json"):
    for r in json.loads(Path(f"/root/gpufree-data/fm_research/{f}").read_text()):
        if r.get("hsv") and r["iou"] >= 0.3:
            hsv[r["id"]] = r["hsv"]
eval_ids = [i for i, c in cases.items() if c["split"] in ("test", "validation")]
pos = [i for i in eval_ids if cases[i]["present"] and i in hsv]
neg = [i for i in eval_ids if not cases[i]["present"]]
print("pos", len(pos), "neg", len(neg), flush=True)

# ---- A: scale sweep ----
A = []
SKIP_A = "--skip-a" in sys.argv
fa = (OUT / "scale_rows.jsonl").open("w")
for i in ([] if SKIP_A else pos + neg):
    c = cases[i]; bgr = cv2.imread(c["image_path"]); gt = hsv.get(i)
    for s in (1, 2, 3):
        im = bgr if s == 1 else cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        ans, lat = chat(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)), native(c["color"]))
        m = BOX.search(ans); row = dict(id=i, color=c["color"], present=c["present"], scale=s, answer=ans, latency=lat)
        if m:
            v = [int(x) for x in m.groups()]; p = [v[0] * .64, v[1] * .48, v[2] * .64, v[3] * .48]
            row["pred"] = p
            if gt:
                row.update(iou=iou(p, gt), cerr=cerr(p, gt), gate=gate(p, gt), gt_max=max(gt[2]-gt[0], gt[3]-gt[1]),
                           cin=gt[0] <= (p[0]+p[2])/2 <= gt[2] and gt[1] <= (p[1]+p[3])/2 <= gt[3])
        A.append(row); fa.write(json.dumps(row, ensure_ascii=False) + "\n"); fa.flush()
    print("A", i, flush=True)

# ---- B: tile presence heatmap ----
TW, TH = 224, 224
xs = np.linspace(0, 640 - TW, 5).astype(int); ys = np.linspace(0, 480 - TH, 3).astype(int)
B = []
fb = (OUT / "tile_rows.jsonl").open("w")
for i in pos + neg:
    c = cases[i]; bgr = cv2.imread(c["image_path"]); gt = hsv.get(i)
    wins = [(int(x), int(y), int(x + TW), int(y + TH)) for y in ys for x in xs]
    imgs = [Image.fromarray(cv2.cvtColor(cv2.resize(bgr[w[1]:w[3], w[0]:w[2]], (448, 448), interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB)) for w in wins]
    p, top, lat = presence_logits(imgs, yesno(c["color"]))
    full_p, full_top, full_lat = presence_logits([Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))], yesno(c["color"]))
    row = dict(id=i, color=c["color"], present=c["present"], p=p, top=top, latency=lat, full_p=full_p[0], full_top=full_top[0], full_latency=full_lat)
    if gt:
        gc = ((gt[0]+gt[2])/2, (gt[1]+gt[3])/2)
        contains = [bool(w[0] <= gc[0] <= w[2] and w[1] <= gc[1] <= w[3]) for w in wins]
        k = int(np.argmax(p)); row.update(top_tile_contains=contains[k], max_p_on=max(q for q, ct in zip(p, contains) if ct) if any(contains) else None,
                                          max_p_off=max([q for q, ct in zip(p, contains) if not ct] or [0]))
        wsum = sum(p) or 1
        cx = sum(q * (w[0]+w[2])/2 for q, w in zip(p, wins)) / wsum; cy = sum(q * (w[1]+w[3])/2 for q, w in zip(p, wins)) / wsum
        row["centroid_err"] = math.hypot(cx - gc[0], cy - gc[1])
    B.append(row); fb.write(json.dumps(row, ensure_ascii=False) + "\n"); fb.flush()
    print("B", i, "%.2f" % lat, flush=True)

S = {}
for s in (() if SKIP_A else (1, 2, 3)):
    rp = [r for r in A if r["scale"] == s and r["present"]]; ok = [r for r in rp if "iou" in r]
    rn = [r for r in A if r["scale"] == s and not r["present"]]
    S[f"scale{s}"] = dict(n=len(rp), parsed=len(ok), gate=sum(r["gate"] for r in ok), cin=sum(r["cin"] for r in ok),
                          cerr_med=statistics.median([r["cerr"] for r in ok]) if ok else None,
                          gate_by_color={col: f"{sum(r.get('gate',False) for r in rp if r['color']==col)}/{sum(r['color']==col for r in rp)}" for col in CN},
                          neg_false_box=f"{sum('pred' in r for r in rn)}/{len(rn)}",
                          lat_med=statistics.median([r["latency"] for r in rp + rn]))
bp = [r for r in B if r["present"]]; bn = [r for r in B if not r["present"]]
S["tiles"] = dict(n=len(bp), top_tile_contains=sum(r["top_tile_contains"] for r in bp),
                  on_gt_p_med=statistics.median([r["max_p_on"] for r in bp if r["max_p_on"] is not None]),
                  off_gt_p_med=statistics.median([r["max_p_off"] for r in bp]),
                  neg_max_p_med=statistics.median([max(r["p"]) for r in bn]) if bn else None,
                  neg_any_tile_gt_0p5=f"{sum(max(r['p'])>0.5 for r in bn)}/{len(bn)}",
                  centroid_err_med=statistics.median([r["centroid_err"] for r in bp]),
                  batch15_latency_med=statistics.median([r["latency"] for r in B]),
                  full_presence_pos_gt_0p5=f"{sum(r['full_p']>0.5 for r in bp)}/{len(bp)}",
                  full_presence_neg_gt_0p5=f"{sum(r['full_p']>0.5 for r in bn)}/{len(bn)}",
                  full_latency_med=statistics.median([r["full_latency"] for r in B]))
(OUT / "summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1))
print(json.dumps(S, ensure_ascii=False, indent=1))
