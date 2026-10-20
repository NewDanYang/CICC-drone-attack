#!/usr/bin/env python3
"""Summarize real trial odometry distances to the surveyed purple balloon."""

import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
import statistics


def parse_time(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("planning_csv", type=Path)
    parser.add_argument("--kind", choices=["baseline_probe", "truth_bridge"], required=True)
    args = parser.parse_args()
    with args.planning_csv.open(encoding="utf-8-sig", newline="") as stream:
        stages = list(csv.DictReader(stream))
    stage = next(x for x in stages if x["stage_name"] == "balloon_positioning_planning")
    begin, end = parse_time(stage["start_time"]), parse_time(stage["end_time"])
    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines()]
    samples = []
    for row in rows:
        if row.get("event") != "sample" or row.get("odom_position") is None:
            continue
        if args.kind == "baseline_probe":
            candidates = [entry for actor_id, obj in row["actors"].items()
                          if obj is not None and abs(obj["center"][1] + 2.1) < 0.45
                          for entry in [[obj["center"][0], obj["center"][1],
                                         -obj["center"][2]]]]
        else:
            candidates = [entry["world"] for entry in row["published"]
                          if entry["color"] == "purple"]
        for position in candidates:
            samples.append({"utc": row["utc"],
                            "distance_m": math.dist(row["odom_position"], position),
                            "odom": row["odom_position"], "balloon": position})
    stage_samples = [x for x in samples if begin <= parse_time(x["utc"]) <= end]
    summary = {"kind": args.kind, "rows": len(rows), "distance_samples": len(samples),
               "balloon_stage_start": stage["start_time"],
               "balloon_stage_end": stage["end_time"],
               "balloon_stage_duration_s": float(stage["duration"]),
               "balloon_stage_distance_samples": len(stage_samples)}
    for name, group in [("all", samples), ("balloon_stage", stage_samples)]:
        summary[name + "_min"] = min(group, key=lambda x: x["distance_m"]) if group else None
        summary[name + "_median_m"] = statistics.median(x["distance_m"] for x in group) if group else None
        summary[name + "_under_0p8m"] = sum(x["distance_m"] < 0.8 for x in group)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
