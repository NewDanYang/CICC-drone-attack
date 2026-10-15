#!/usr/bin/env python3
"""Emit raw ArUco ROS events from the nine official telemetry files."""
import json
from pathlib import Path

root = Path("/home/ubuntu/tcei_baseline_tools/results/formal_trials")
for directory in sorted(root.glob("20261015T*_A0")):
    for path in directory.glob("*_telemetry.jsonl"):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "rosout" and event.get("name") == "/aruco_detect_node":
                    event["trial_dir"] = directory.name
                    event["source_telemetry"] = str(path)
                    print(json.dumps(event, ensure_ascii=False))
