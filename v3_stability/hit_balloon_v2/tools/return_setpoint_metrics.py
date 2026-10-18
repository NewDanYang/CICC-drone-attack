#!/usr/bin/env python3
"""Measure the landing return's position-setpoint distance from recorded odom.

Usage: python3 return_setpoint_metrics.py TRIAL_TELEMETRY.jsonl
This reads a completed formal trial; it never connects to ROS or the simulator.
"""

import bisect
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys


def stamp(row):
    return datetime.fromisoformat(row["wall_time"]).timestamp()


def distance(a, b):
    return math.sqrt(sum((a[axis] - b[axis]) ** 2 for axis in ("x", "y", "z")))


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    starts = [stamp(row) for row in rows if row.get("event") == "rosout"
              and "GoTo start -> target: (0.00, 0.00, 0.50)" in row.get("message", "")]
    if len(starts) != 1:
        raise SystemExit(f"expected one landing return, got {len(starts)}")
    start = starts[0]
    end = next((stamp(row) for row in rows if row.get("event") == "rosout"
                and stamp(row) > start and "[GoTo]: GoTo completed" in row.get("message", "")), None)
    if end is None:
        raise SystemExit("landing return did not complete")
    odom = [(stamp(row), row) for row in rows if row.get("event") == "odom_sample"
            and row.get("topic") == "/mavros/local_position/odom" and start <= stamp(row) <= end]
    times = [item[0] for item in odom]
    values = []
    timing_errors = []
    for row in rows:
        if row.get("event") != "setpoint_sample" or row.get("topic") != "/mavros/setpoint_raw/local":
            continue
        t = stamp(row)
        if not start <= t <= end or not odom:
            continue
        i = bisect.bisect_left(times, t)
        nearest = min((j for j in (i - 1, i) if 0 <= j < len(odom)), key=lambda j: abs(times[j] - t))
        delta = abs(times[nearest] - t)
        if delta > 0.10:
            continue
        values.append(distance(row["position"], odom[nearest][1]["position"]))
        timing_errors.append(delta)
    if not values:
        raise SystemExit("no matched return setpoints")
    ordered = sorted(values)
    print(json.dumps({
        "telemetry": str(path),
        "return_start_utc": datetime.fromtimestamp(start, timezone.utc).isoformat(),
        "return_end_utc": datetime.fromtimestamp(end, timezone.utc).isoformat(),
        "matched_samples": len(values),
        "max_odom_match_gap_s": round(max(timing_errors), 4),
        "max_setpoint_distance_m": round(max(values), 3),
        "p95_setpoint_distance_m": round(ordered[int(0.95 * (len(ordered) - 1))], 3),
        "median_setpoint_distance_m": round(statistics.median(values), 3),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
