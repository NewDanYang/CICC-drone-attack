#!/usr/bin/env python3
"""P14: why do some visible segments never get acquired? Probe presence on the actual frames at several tile scales."""
import json, sys
from pathlib import Path
import cv2, numpy as np, torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer
sys.path.insert(0, str(Path(__file__).parent))
from fastpresence import FastPresence

MODEL = "/home/ubuntu/model/FM9G4B-V"
CN = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026")
CASES = [("04_r1_purple_baseline", range(36, 43)), ("09_r2_purple_baseline", range(104, 110)),
         ("17_r3_blue_baseline", range(1, 4)), ("05_r1_blue_baseline", range(0, 5)),
         ("09_r2_purple_baseline", range(183, 215, 3)), ("16_r3_purple_baseline", range(143, 152)),
         ("09_r2_purple_baseline", range(70, 76))]   # last = control: acquired fine
tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16).cuda().eval()
fp = FastPresence(model, tok, proc, res=224); fp448 = FastPresence(model, tok, proc, res=448)


def crops(frame, wins, res):
    return torch.stack([torch.nn.functional.interpolate(frame[w[1]:w[3], w[0]:w[2]].permute(2, 0, 1)[None].float(), size=(res, res),
                        mode="bilinear", align_corners=False)[0].permute(1, 2, 0).round().clamp(0, 255).byte() for w in wins])


T224 = [(int(x), int(y), int(x) + 224, int(y) + 224) for y in np.linspace(0, 256, 3) for x in np.linspace(0, 416, 5)]
T448 = [(int(x), 16, int(x) + 448, 464) for x in np.linspace(0, 192, 3)]
T320 = [(int(x), int(y), int(x) + 320, int(y) + 320) for y in (0, 160) for x in (0, 160, 320)]
for run, idx in CASES:
    color = run.split("_")[2]; text = f"这张图片里有没有{CN[color]}的气球？只回答“是”或“否”。"
    d = ROOT / run / "audit"; ev = [json.loads(l) for l in open(d / "events.jsonl")]
    a = next(e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", ""))
    fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
    yolo = [e for e in ev if e["event"] == "objects" and e.get("topic") == "yolo"]
    for k in idx:
        e = fr[k]; m = [y for y in yolo if abs(y["stamp"] - e["header_stamp"]) < 0.06]
        g = [x["bbox"] for x in (min(m, key=lambda y: abs(y["stamp"] - e["header_stamp"]))["objects"] if m else []) if x["name"] == color + "_balloon"]
        bgr = cv2.imread(str(d / e["file"])); f = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).cuda()
        pf = fp448(f[None], text)[0]
        p224 = fp(crops(f, T224, 224), text); p320 = fp(crops(f, T320, 224), text); p448 = fp(crops(f, T448, 224), text)
        print(f"{run[:12]} k={k:3d} gt={g[0] if g else None} full={pf:.2f} max224={max(p224):.2f} "
              f"n224>.5={sum(p >= .5 for p in p224)} max320={max(p320):.2f} max448={max(p448):.2f}", flush=True)
