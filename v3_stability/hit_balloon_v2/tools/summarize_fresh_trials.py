#!/usr/bin/env python3
"""Summarize fresh-scene formal trials without inferring balloon colors from IDs."""
import argparse
import csv
import json
from pathlib import Path
import re


FIELDS = [
    "batch", "round", "color", "attempt", "trial_dir", "run_id", "sim_pid", "before",
    "after", "settled", "removed_count", "added_count", "frame_count",
    "runner_rc", "mission_success", "hit_balloon_status", "land_status",
    "boundary_violation_count", "sprint_starts", "sprint_ends", "sprint_aborts",
    "boundary_pre_servo_count", "boundary_after_servo_start_count",
    "boundary_after_sprint_count", "tracked_pixels", "servo_start_time",
    "first_sprint_time", "first_sprint_abort_time", "first_sprint_abort_reason",
    "first_boundary_time",
    "telemetry_path", "snapshots_path", "frames_path", "judge_hit",
]


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def summarize(loop_dir):
    baseline = loop_dir.parent / "baseline_runs.csv"
    with baseline.open(newline="", encoding="utf-8-sig") as stream:
        runs = {r["run_id"]: r for r in csv.DictReader(stream)}
    with (loop_dir / "trials.csv").open(newline="", encoding="utf-8") as stream:
        attempts = list(csv.DictReader(stream))
    for attempt in attempts:
        trial = Path(attempt["trial_dir"])
        if not trial.is_dir():
            continue
        observer = (trial / "observer.out").read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^run_id=(\S+)", observer, re.MULTILINE)
        run_id = match.group(1) if match else ""
        baseline_row = runs.get(run_id, {})
        snaps_path = trial / "scene_snapshots.jsonl"
        snaps = list(read_jsonl(snaps_path)) if snaps_path.exists() else []
        phases = {s["phase"]: s for s in snaps}
        before = phases.get("before", {})
        after = phases.get("after", {})
        settled = phases.get("settled", {})
        removed = set(before.get("actor_ids", [])) - set(settled.get("actor_ids", []))
        added = set(settled.get("actor_ids", [])) - set(before.get("actor_ids", []))
        telemetry_paths = list(trial.glob("*telemetry.jsonl"))
        starts, ends, aborts, boundaries, servo_starts, tracked = [], [], [], [], [], 0
        if len(telemetry_paths) == 1:
            for event in read_jsonl(telemetry_paths[0]):
                if event.get("event") != "rosout":
                    continue
                message = event.get("message", "")
                if "SPRINT_START" in message:
                    starts.append(event["wall_time"])
                if "Visual Servo Started" in message:
                    servo_starts.append(event["wall_time"])
                if "SPRINT_END" in message:
                    ends.append(event["wall_time"])
                if "SPRINT_ABORT_NEAR_TARGET" in message:
                    aborts.append((event["wall_time"], message))
                if "DRONE OUT OF BOUNDARY" in message:
                    boundaries.append(event["wall_time"])
                if "[TargetTracker]: Tracking at pixel" in message:
                    tracked += 1
        frame_path = trial / "real_frames" / "frames.jsonl"
        frame_count = sum(1 for _ in read_jsonl(frame_path)) if frame_path.exists() else 0
        judgement_path = trial / "judgement.json"
        judgement = json.loads(judgement_path.read_text(encoding="utf-8")) if judgement_path.exists() else {}
        yield {
            "batch": loop_dir.name,
            "round": attempt["round"], "color": attempt["color"],
            "attempt": attempt["attempt"], "trial_dir": str(trial), "run_id": run_id,
            "sim_pid": before.get("sim_pid", attempt["sim_pid"]),
            "before": before.get("reported_count", ""),
            "after": after.get("reported_count", ""),
            "settled": settled.get("reported_count", ""),
            "removed_count": len(removed) if before and settled else "",
            "added_count": len(added) if before and settled else "",
            "frame_count": frame_count, "runner_rc": attempt["runner_rc"],
            "mission_success": baseline_row.get("mission_success", ""),
            "hit_balloon_status": baseline_row.get("hit_balloon_status", ""),
            "land_status": baseline_row.get("land_status", ""),
            "boundary_violation_count": baseline_row.get("boundary_violation_count", ""),
            "sprint_starts": len(starts), "sprint_ends": len(ends),
            "sprint_aborts": len(aborts),
            "boundary_pre_servo_count": sum(t < servo_starts[0] for t in boundaries) if servo_starts else "",
            "boundary_after_servo_start_count": sum(t >= servo_starts[0] for t in boundaries) if servo_starts else "",
            "boundary_after_sprint_count": sum(t >= starts[0] for t in boundaries) if starts else "",
            "tracked_pixels": tracked,
            "servo_start_time": servo_starts[0] if servo_starts else "",
            "first_sprint_time": starts[0] if starts else "",
            "first_sprint_abort_time": aborts[0][0] if aborts else "",
            "first_sprint_abort_reason": re.search(r"reason=(\w+)", aborts[0][1]).group(1) if aborts else "",
            "first_boundary_time": boundaries[0] if boundaries else "",
            "telemetry_path": str(telemetry_paths[0]) if len(telemetry_paths) == 1 else "",
            "snapshots_path": str(snaps_path) if snaps_path.exists() else "",
            "frames_path": str(frame_path) if frame_path.exists() else "",
            "judge_hit": judgement.get("hit", ""),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("loop_dir", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [row for loop_dir in args.loop_dir for row in summarize(loop_dir)]
    output = args.output.open("w", encoding="utf-8", newline="") if args.output else None
    try:
        writer = csv.DictWriter(output or __import__("sys").stdout, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    main()
