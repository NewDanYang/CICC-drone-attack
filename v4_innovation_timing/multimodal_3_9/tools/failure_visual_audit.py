#!/usr/bin/env python3
"""Audit self-check target appearance, duplicate labels, and raw predictions."""
from __future__ import annotations

import colorsys
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

BOX_RE = re.compile(r"<box>\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*</box>")


def iou(a, b):
    x = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = x * y
    ua = (a[2] - a[0]) * (a[3] - a[1])
    ub = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (ua + ub - inter) if ua + ub - inter else 0.0


def crop_hues(path, bbox):
    from PIL import Image

    im = Image.open(path).convert("RGB")
    x1, y1, x2, y2 = bbox
    hues = []
    for y in range(y1 + 2, min(y2 - 1, im.height)):
        for x in range(x1 + 2, min(x2 - 1, im.width)):
            r, g, b = [v / 255 for v in im.getpixel((x, y))]
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            if s > 0.35 and v > 0.15:
                hues.append(h * 360)
    return {
        "n_saturated_pixels": len(hues),
        "hue_median_deg": statistics.median(hues) if hues else None,
        "hue_min_deg": min(hues) if hues else None,
        "hue_max_deg": max(hues) if hues else None,
    }


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--all-cases", type=Path)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--scored", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    all_cases = json.loads(args.all_cases.read_text(encoding="utf-8")) if args.all_cases else cases
    by_id = {r["id"]: r for r in cases}
    by_image = defaultdict(list)
    for r in all_cases:
        by_image[r["image"]].append(r)
    predictions = {}
    for line in args.predictions.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        predictions[r["id"]] = r["prediction"]
    scored = json.loads(args.scored.read_text(encoding="utf-8"))
    items = []
    for s in scored:
        row = by_id.get(s["id"])
        if row is None:
            row = by_id[s["id"].replace("_selfcheck_native", "")]
        base_id = row["id"].replace("_selfcheck_native", "")
        other_labels = []
        for other in by_image[row["image"]]:
            if other["id"] == base_id or not other.get("bbox") or not row.get("bbox"):
                continue
            other_labels.append({
                "id": other["id"], "color": other["color"],
                "bbox": other["bbox"], "iou": iou(row["bbox"], other["bbox"]),
            })
        m = BOX_RE.search(predictions[s["id"]])
        items.append({
            "id": s["id"], "image": row["image"], "label_color": row["color"],
            "label_bbox_px": row["bbox"],
            "geometry_pass": s["geometry_pass"], "iou": s.get("iou"),
            "center_error_px": s.get("center_error_px"),
            "raw_prediction": predictions[s["id"]],
            "raw_prediction_bbox_norm_1000": [int(x) for x in m.groups()] if m else None,
            "target_crop_hue": crop_hues(args.images / row["image"], row["bbox"]),
            "other_labels_same_image": other_labels,
        })
    out = {
        "n": len(items),
        "geometry_pass": sum(x["geometry_pass"] for x in items),
        "items": items,
        "failure_ids": [x["id"] for x in items if not x["geometry_pass"]],
    }
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n": out["n"], "geometry_pass": out["geometry_pass"], "failure_ids": out["failure_ids"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
