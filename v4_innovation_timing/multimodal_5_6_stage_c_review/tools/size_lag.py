#!/usr/bin/env python3
"""Where does size get lost for big balloons? model decision box (at its own source frame) vs published CSRT box."""
import glob, json, statistics as st, sys
from pathlib import Path

ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026")
RUNS = ["04_r1_purple_baseline", "05_r1_blue_baseline", "08_r2_red_baseline", "09_r2_purple_baseline",
        "12_r2_blue_baseline", "13_r3_red_baseline", "16_r3_purple_baseline", "17_r3_blue_baseline"]
dec_r, pub_r, dec_mode = [], [], {"acquire": [], "track": []}
for run in RUNS:
    color = run.split("_")[2]; d = ROOT / run / "audit"
    ev = [json.loads(l) for l in open(d / "events.jsonl")]
    a = next(e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", ""))
    fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
    yolo = [e for e in ev if e["event"] == "objects" and e.get("topic") == "yolo"]

    def gt(k):
        e = fr[k - 1]; m = [y for y in yolo if abs(y["stamp"] - e["header_stamp"]) < 0.06]
        if not m:
            return None
        o = [x for x in min(m, key=lambda y: abs(y["stamp"] - e["header_stamp"]))["objects"] if x["name"] == color + "_balloon"]
        return o[0]["bbox"] if o else None

    for aud in glob.glob(f"{sys.argv[1]}/*_{run}"):
        f = glob.glob(aud + "/**/audit.jsonl", recursive=True)[0]
        for l in open(f):
            e = json.loads(l)
            k = e.get("source_frame") if e.get("kind") == "decision" else (e.get("frame_seq") if e.get("kind") == "publish" else None)
            b = e.get("bbox")
            if not k or not b or k > len(fr):
                continue
            g = gt(k)
            if not g or max(g[2] - g[0], g[3] - g[1]) < 80:
                continue
            r = ((b[2] - b[0]) * (b[3] - b[1])) / ((g[2] - g[0]) * (g[3] - g[1]))
            if e["kind"] == "decision":
                dec_r.append(r); dec_mode[e["mode"]].append(r)
            else:
                pub_r.append(r)
print("big balloons (YOLO >=80px):")
print("  model decision box / YOLO at its own frame: n=%d median %.2f" % (len(dec_r), st.median(dec_r)))
for m, v in dec_mode.items():
    if v:
        print("     %s n=%d median %.2f" % (m, len(v), st.median(v)))
print("  published (CSRT-interpolated) box / YOLO:   n=%d median %.2f" % (len(pub_r), st.median(pub_r)))
