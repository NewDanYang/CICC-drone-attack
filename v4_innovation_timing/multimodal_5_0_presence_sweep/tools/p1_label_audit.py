#!/usr/bin/env python3
"""P1: compare existing balloon labels with tight offline HSV-mask boxes (label-only, never runtime)."""
import json, math, statistics, sys, cv2, numpy as np
from pathlib import Path

# OpenCV hue 0-179. red wraps; purple/magenta ~145-160; blue balloon ~115-125 (banner cyan ~95-105, low risk).
HUE = {"red": [(0, 8), (170, 179)], "purple": [(138, 165)], "blue": [(108, 130)]}


def mask(bgr, color):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in HUE[color]:
        m |= cv2.inRange(hsv, (lo, 110, 40), (hi, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return m


def blobs(m, min_area=30):
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    return [dict(box=[int(st[i, 0]), int(st[i, 1]), int(st[i, 0] + st[i, 2]), int(st[i, 1] + st[i, 3])],
                 area=int(st[i, 4])) for i in range(1, n) if st[i, 4] >= min_area]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def cerr(a, b):
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


def gate(pred, gt):
    return iou(pred, gt) >= 0.5 and cerr(pred, gt) <= max(8, 0.2 * math.hypot(gt[2] - gt[0], gt[3] - gt[1]))


root = Path(sys.argv[1])  # dataset dir with cases.json
img_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
cases = json.loads((root / "cases.json").read_text())
out = []
for c in cases:
    if not c.get("bbox"):
        continue
    p = c.get("image_path") or str((img_dir or root) / c["image"])
    im = cv2.imread(p)
    if im is None:
        continue
    bl = blobs(mask(im, c["color"]))
    best = max(bl, key=lambda b: iou(b["box"], c["bbox"]), default=None)
    r = dict(id=c.get("id", c["image"]), split=c["split"], color=c["color"], label=c["bbox"], n_blobs=len(bl))
    if best:
        r.update(hsv=best["box"], iou=iou(best["box"], c["bbox"]), cerr=cerr(best["box"], c["bbox"]),
                 label_passes_gate_vs_hsv=gate(c["bbox"], best["box"]))
    out.append(r)
for sp in sorted({r["split"] for r in out}):
    rs = [r for r in out if r["split"] == sp]
    m = [r for r in rs if "iou" in r]
    print(sp, "n", len(rs), "matched", len(m),
          "median_iou %.3f" % statistics.median([r["iou"] for r in m]) if m else "",
          "median_cerr %.2f" % statistics.median([r["cerr"] for r in m]) if m else "",
          "label_gate_vs_hsv %d/%d" % (sum(r["label_passes_gate_vs_hsv"] for r in m), len(m)))
    for col in ("red", "purple", "blue"):
        mc = [r for r in m if r["color"] == col]
        if mc:
            print("  ", col, len(mc), "iou_med %.3f" % statistics.median([r["iou"] for r in mc]),
                  "gate %d" % sum(r["label_passes_gate_vs_hsv"] for r in mc),
                  "low_iou<0.5:", [r["id"] for r in mc if r["iou"] < 0.5][:6])
Path(sys.argv[-1] if sys.argv[-1].endswith(".json") else "/tmp/p1_out.json").write_text(json.dumps(out, indent=1))
