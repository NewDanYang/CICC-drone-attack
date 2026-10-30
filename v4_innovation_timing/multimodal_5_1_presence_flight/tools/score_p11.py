#!/usr/bin/env python3
"""Score P10/P11 replay rows against the recorded YOLO reference.

YOLO is read only here as an offline reference.  No runtime code imports this
module.  The trailing absent-frame count is a conservative proxy for the
manually confirmed leave segments in the P10 contact sheet; it is reported
separately from the visible-frame precision metrics.
"""
import json, math, statistics, sys
from pathlib import Path

RUNS = ["01_r1_red_baseline", "04_r1_purple_baseline", "05_r1_blue_baseline", "08_r2_red_baseline", "09_r2_purple_baseline", "12_r2_blue_baseline", "13_r3_red_baseline", "16_r3_purple_baseline", "17_r3_blue_baseline"]
COLORS = {"red", "purple", "blue"}

def area(b):
    return max(0.0, (b[2] - b[0]) * (b[3] - b[1]))

def score_dir(root):
    root = Path(root); per_run = {}; all_rows = []
    for run in RUNS:
        rows = json.loads((root / f"{run}.json").read_text())["rows"]
        color = run.split("_")[2]
        vis = [r for r in rows if isinstance(r.get("gt"), list)]
        pubv = [r for r in vis if isinstance(r.get("pub"), list)]
        cin = [r for r in vis if r.get("cin")]
        ratios = [area(r["pub"]) / area(r["gt"]) for r in pubv if area(r["gt"]) > 0]
        # The final contiguous YOLO-visible segment is the only one used for
        # residual publishing after a confirmed leave.  Nodata frames are not
        # treated as a leave confirmation.
        last = max((i for i, r in enumerate(rows) if isinstance(r.get("gt"), list)), default=None)
        tail = []
        if last is not None:
            j = last + 1
            while j < len(rows) and rows[j].get("gt") is None:
                tail.append(rows[j]); j += 1
        # First visible segment to first center-correct publication.
        latencies = []
        center_latencies = []
        i = 0
        while i < len(rows):
            if not isinstance(rows[i].get("gt"), list): i += 1; continue
            start = i
            while i + 1 < len(rows) and isinstance(rows[i + 1].get("gt"), list): i += 1
            first = next((r for r in rows[start:i + 1] if isinstance(r.get("pub"), list)), None)
            good = next((r for r in rows[start:i + 1] if r.get("cin")), None)
            if first is not None: latencies.append(first["t"] - rows[start]["t"])
            if good is not None: center_latencies.append(good["t"] - rows[start]["t"])
            i += 1
        p = dict(run=run, color=color, frames=len(rows), visible=len(vis), published_visible=len(pubv), center_inside=len(cin),
                 center_ratio=(len(cin) / len(vis) if vis else None), publish_precision=(len(cin) / len(pubv) if pubv else None),
                 area_ratio_median=(statistics.median(ratios) if ratios else None), tail_absent_frames=len(tail), tail_published=sum(bool(r.get("pub")) for r in tail),
                 acquisition_latency_median=(statistics.median(latencies) if latencies else None), acquisition_latency_max=(max(latencies) if latencies else None), center_latency_median=(statistics.median(center_latencies) if center_latencies else None))
        per_run[run] = p; all_rows.extend((color, r) for r in rows)
    vis = sum(p["visible"] for p in per_run.values()); pubv = sum(p["published_visible"] for p in per_run.values()); cin = sum(p["center_inside"] for p in per_run.values())
    area_vals = []
    for run in RUNS:
        rows = json.loads((root / f"{run}.json").read_text())["rows"]
        area_vals.extend(area(r["pub"]) / area(r["gt"]) for r in rows if isinstance(r.get("gt"), list) and isinstance(r.get("pub"), list) and area(r["gt"]) > 0)
    tail_vals = [p["tail_published"] for p in per_run.values() if p["visible"]]
    lat_vals = [p["acquisition_latency_median"] for p in per_run.values() if p["acquisition_latency_median"] is not None]
    by_color = {}
    for c in sorted(COLORS):
        q = [p for p in per_run.values() if p["color"] == c]
        by_color[c] = dict(visible=sum(x["visible"] for x in q), published_visible=sum(x["published_visible"] for x in q), center_inside=sum(x["center_inside"] for x in q), center_ratio=sum(x["center_inside"] for x in q) / max(1, sum(x["visible"] for x in q)), publish_precision=sum(x["center_inside"] for x in q) / max(1, sum(x["published_visible"] for x in q)))
    return dict(root=str(root), total=dict(visible=vis, published_visible=pubv, center_inside=cin, center_ratio=cin / max(1, vis), publish_precision=cin / max(1, pubv), area_ratio_median=(statistics.median(area_vals) if area_vals else None), tail_published_median=(statistics.median(tail_vals) if tail_vals else None), tail_published_max=(max(tail_vals) if tail_vals else None), acquisition_latency_median=(statistics.median(lat_vals) if lat_vals else None)), by_color=by_color, per_run=per_run)

if __name__ == "__main__":
    out = {Path(x).name: score_dir(x) for x in sys.argv[1:]}
    print(json.dumps(out, indent=2, ensure_ascii=False))
