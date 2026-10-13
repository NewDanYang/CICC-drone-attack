"""Summarize real ArUco callback windows in formal trial telemetry."""
import glob
import json
import pathlib
import re
import sys
from datetime import datetime


def summarize(directory):
    files = glob.glob(str(pathlib.Path(directory) / "*telemetry.jsonl"))
    if len(files) != 1:
        return {"directory": str(directory), "error": "expected one telemetry file"}
    windows, current = [], None
    for line in open(files[0], encoding="utf-8"):
        row = json.loads(line)
        if row.get("event") != "rosout" or row.get("name") != "/aruco_detect_node":
            continue
        msg = row.get("message", "")
        if "Detection ENABLED" in msg:
            current = {"enabled_at": row["wall_time"], "rates_per_s": []}
        elif current is not None and "callbacks/s=" in msg:
            match = re.search(r"callbacks/s=([0-9.]+)", msg)
            if match:
                current["rates_per_s"].append(float(match.group(1)))
        elif current is not None and "Detection DISABLED" in msg:
            current["disabled_at"] = row["wall_time"]
            current["duration_s"] = (datetime.fromisoformat(row["wall_time"])
                                      - datetime.fromisoformat(current["enabled_at"])).total_seconds()
            match = re.search(r"callbacks=(\d+) decode_fail=(\d+)", msg)
            if match:
                current["callback_count"] = int(match.group(1))
                current["decode_fail"] = int(match.group(2))
            current["zero_rate_count"] = current["rates_per_s"].count(0.0)
            windows.append(current)
            current = None
    return {"directory": str(directory), "windows": windows,
            "incomplete_window": current}


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(json.dumps(summarize(arg), ensure_ascii=False))
