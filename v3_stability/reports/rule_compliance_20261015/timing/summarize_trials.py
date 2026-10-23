#!/usr/bin/env python3
"""Summarize the 2026-10-15 formal-trial telemetry without affecting the simulation."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import sys


ROOT = Path("/home/ubuntu/tcei_baseline_tools/results")
fields = [
    "trial_dir", "color", "run_id", "window_s", "callbacks", "decode_fail",
    "total_time_s", "takeoff", "cross_frame", "detect_aruco",
    "return_cross_frame", "hit_balloon", "land", "mission_success",
    "boundary_violation_count", "proxy_hit", "removed_count",
]


def main():
    with (ROOT / "baseline_runs.csv").open(newline="", encoding="utf-8") as handle:
        runs = {r["run_id"]: r for r in csv.DictReader(handle)}
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    for directory in sorted((ROOT / "formal_trials").glob("20261015T*_A0")):
        telemetry_paths = list(directory.glob("*_telemetry.jsonl"))
        if len(telemetry_paths) != 1:
            continue
        observer_path = directory / "observer.out"
        observer_text = observer_path.read_text(encoding="utf-8", errors="replace") if observer_path.exists() else ""
        run_match = re.search(r"^run_id=(\S+)", observer_text, re.MULTILINE)
        run_id = run_match.group(1) if run_match else ""
        row = runs.get(run_id, {})
        enabled = disabled = None
        callbacks = decode_fail = None
        with telemetry_paths[0].open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") != "rosout" or event.get("name") != "/aruco_detect_node":
                    continue
                message = event.get("message", "")
                if "Detection ENABLED" in message:
                    enabled = datetime.fromisoformat(event["wall_time"].replace("Z", "+00:00"))
                elif "Detection DISABLED" in message:
                    disabled = datetime.fromisoformat(event["wall_time"].replace("Z", "+00:00"))
                    match = re.search(r"callbacks=(\d+) decode_fail=(\d+)", message)
                    if match:
                        callbacks, decode_fail = map(int, match.groups())
        judgement_path = directory / "judgement.json"
        judgement = json.loads(judgement_path.read_text(encoding="utf-8")) if judgement_path.exists() else {}
        snapshots = judgement.get("evidence", {}).get("scene_snapshots", {}) or {}
        out = {
            "trial_dir": directory.name,
            "color": directory.name.split("_")[1],
            "run_id": run_id,
            "window_s": round((disabled - enabled).total_seconds(), 3) if enabled and disabled else "",
            "callbacks": callbacks if callbacks is not None else "",
            "decode_fail": decode_fail if decode_fail is not None else "",
            "total_time_s": row.get("total_time", ""),
            "takeoff": row.get("takeoff_status", ""),
            "cross_frame": row.get("cross_frame_status", ""),
            "detect_aruco": row.get("detect_aruco_status", ""),
            "return_cross_frame": row.get("return_cross_frame_status", ""),
            "hit_balloon": row.get("hit_balloon_status", ""),
            "land": row.get("land_status", ""),
            "mission_success": row.get("mission_success", ""),
            "boundary_violation_count": row.get("boundary_violation_count", ""),
            "proxy_hit": judgement.get("hit", ""),
            "removed_count": len(snapshots.get("removed", [])) if judgement_path.exists() else "",
        }
        writer.writerow(out)


if __name__ == "__main__":
    main()
