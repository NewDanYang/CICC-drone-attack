#!/usr/bin/env python3
"""P13: does a stricter presence prompt reject the blue banner logo while keeping real balloons? (05 blue + 12/17 blue)"""
import json, sys
from pathlib import Path
import cv2, numpy as np, torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer
sys.path.insert(0, str(Path(__file__).parent))
from fastpresence import FastPresence

MODEL = "/home/ubuntu/model/FM9G4B-V"
tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fp = FastPresence(model, tok, proc, res=224)
PROMPTS = {
    "base": "这张图片里有没有蓝色的气球？只回答“是”或“否”。",
    "round": "这张图片里有没有一个蓝色的、圆形的、立体的气球（不是平面标志、图案或文字）？只回答“是”或“否”。",
    "car": "这张图片里有没有一个系在小车上方的蓝色气球？只回答“是”或“否”。",
}
ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026")
out = {}
for run in ("05_r1_blue_baseline", "12_r2_blue_baseline", "17_r3_blue_baseline"):
    R = json.load(open(f"/root/gpufree-data/fm_research/p12e/{run}.json"))["rows"]
    d = ROOT / run / "audit"; ev = [json.loads(l) for l in open(d / "events.jsonl")]
    a = [e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", "")][0]
    fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
    for r in R:
        if not r["pub"]:
            continue
        kind = "true" if r["cin"] else ("absent" if r["gt"] is None else ("wrong" if isinstance(r["gt"], list) else "nodata"))
        if kind == "nodata":
            continue
        b = r["pub"]; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2; s = int(min(480, max(56, 2.2 * max(b[2] - b[0], b[3] - b[1]))))
        x0 = int(min(max(cx - s / 2, 0), 640 - s)); y0 = int(min(max(cy - s / 2, 0), 480 - s))
        bgr = cv2.imread(str(d / fr[r["k"]]["file"]))
        crop = cv2.cvtColor(cv2.resize(bgr[y0:y0 + s, x0:x0 + s], (224, 224)), cv2.COLOR_BGR2RGB)
        g = torch.from_numpy(crop).cuda()[None]
        for p, t in PROMPTS.items():
            out.setdefault(kind, {}).setdefault(p, []).append(fp(g, t)[0])
for kind, v in out.items():
    print(kind, {p: f"n={len(x)} yes={sum(q >= .5 for q in x)} med={np.median(x):.2f}" for p, x in v.items()}, flush=True)
