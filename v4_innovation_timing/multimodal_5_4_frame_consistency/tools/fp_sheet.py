#!/usr/bin/env python3
"""Contact sheet of publishes made while YOLO saw no target (fp_absent) in patched-runtime audits."""
import glob, json, sys
from pathlib import Path
import cv2, numpy as np

ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026")
out = sys.argv[1]; tiles = []
for aud in sys.argv[2:]:
    run = next(r for r in ("05_r1_blue_baseline", "12_r2_blue_baseline", "17_r3_blue_baseline", "09_r2_purple_baseline",
                           "04_r1_purple_baseline", "16_r3_purple_baseline", "13_r3_red_baseline", "08_r2_red_baseline") if r in aud)
    color = run.split("_")[2]; d = ROOT / run / "audit"
    ev = [json.loads(l) for l in open(d / "events.jsonl")]
    a = next(e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", ""))
    fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
    yolo = [e for e in ev if e["event"] == "objects" and e.get("topic") == "yolo"]
    f = glob.glob(aud + "/**/audit.jsonl", recursive=True)[0]
    for l in open(f):
        e = json.loads(l)
        if e.get("kind") != "publish" or not e.get("bbox"):
            continue
        k = e["frame_seq"] - 1; im = fr[k]
        m = [y for y in yolo if abs(y["stamp"] - im["header_stamp"]) < 0.06]
        if not m:
            continue
        g = [x for x in min(m, key=lambda y: abs(y["stamp"] - im["header_stamp"]))["objects"] if x["name"] == color + "_balloon"]
        if g:
            continue
        bgr = cv2.imread(str(d / im["file"])); b = [int(v) for v in e["bbox"]]
        cv2.rectangle(bgr, (b[0], b[1]), (b[2], b[3]), (0, 255, 0), 2)
        cv2.putText(bgr, f"{run[:6]} k{k+1}", (5, 25), 0, 0.8, (0, 255, 255), 2)
        tiles.append(cv2.resize(bgr, (320, 240)))
print(len(tiles))
tiles = tiles[::max(1, len(tiles) // 24)][:24]
while len(tiles) % 4:
    tiles.append(np.zeros_like(tiles[0]))
cv2.imwrite(out, np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
