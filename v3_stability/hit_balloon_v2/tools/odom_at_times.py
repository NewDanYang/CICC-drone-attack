#!/usr/bin/env python3
"""Read recorded odometry nearest supplied UTC times; never sends flight commands."""

import argparse
import datetime as dt
import json
from pathlib import Path


def parse_time(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("times", nargs="+", help="UTC ISO timestamps")
    args = parser.parse_args()
    targets = [parse_time(t) for t in args.times]
    best = [None for _ in targets]
    for line in args.telemetry.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("event") != "odom_sample" or row.get("topic") != "/mavros/local_position/odom":
            continue
        stamp = parse_time(row["wall_time"])
        for i, target in enumerate(targets):
            delta = abs((stamp - target).total_seconds())
            if best[i] is None or delta < best[i][0]:
                best[i] = (delta, row)
    for input_time, match in zip(args.times, best):
        if match is None:
            print(json.dumps({"requested": input_time, "error": "no odometry"}))
            continue
        delta, row = match
        print(json.dumps({"requested": input_time, "sample_time": row["wall_time"],
                          "delta_s": round(delta, 3), "position": row["position"],
                          "speed": row.get("speed")}))


if __name__ == "__main__":
    main()
