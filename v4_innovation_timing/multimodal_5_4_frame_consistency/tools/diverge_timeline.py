#!/usr/bin/env python3
"""Per-frame timeline of published boxes vs YOLO GT for several audit runs of the same recorded trial."""
import glob, json, sys
from pathlib import Path

ROOT = Path("/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026")
run = sys.argv[1]; audits = sys.argv[2:]
color = run.split("_")[2]
d = ROOT / run / "audit"
ev = [json.loads(l) for l in open(d / "events.jsonl")]
a = next(e["ros_time"] for e in ev if e["event"] == "rosout" and "Visual Servo Started" in e.get("message", ""))
fr = [e for e in ev if e["event"] == "image" and a - 2 <= e["ros_time"] <= a + 50 and (d / e["file"]).exists()]
yolo = [e for e in ev if e["event"] == "objects" and e.get("topic") == "yolo"]


def gt(e):
    m = [y for y in yolo if abs(y["stamp"] - e["header_stamp"]) < 0.06]
    if not m:
        return "nodata"
    o = [x for x in min(m, key=lambda y: abs(y["stamp"] - e["header_stamp"]))["objects"] if x["name"] == color + "_balloon"]
    return o[0]["bbox"] if o else None


G = [gt(e) for e in fr]
lines = []
for path in audits:
    f = glob.glob(path + "/**/audit.jsonl", recursive=True)[0]
    pub = {}
    for l in open(f):
        e = json.loads(l)
        if e.get("kind") == "publish":
            pub[e["frame_seq"]] = e.get("bbox")
    s = ""
    for i, g in enumerate(G, start=1):
        b = pub.get(i)
        c = "-" if g == "nodata" else ("." if g is None else "G")
        if b:
            cin = isinstance(g, list) and g[0] <= (b[0] + b[2]) / 2 <= g[2] and g[1] <= (b[1] + b[3]) / 2 <= g[3]
            c = "P" if cin else ("x" if isinstance(g, list) else "F")
        s += c
    lines.append((path.split("/")[-1][:40], s))
for name, s in lines:
    print(f"{name:40s} {s}")
# print GT boxes and published boxes in the first visible segment for detail
print("frame  gt  |  " + "  |  ".join(n[-10:] for n, _ in lines))
