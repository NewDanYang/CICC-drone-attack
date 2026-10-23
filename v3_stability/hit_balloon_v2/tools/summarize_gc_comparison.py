#!/usr/bin/env python3
"""Compute UE actor-list response times in control and forced-GC trials."""
import argparse
import datetime as dt
import json
from pathlib import Path
import statistics


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value):
    return value.isoformat(timespec="milliseconds") if value else ""


def summarize(mode_dir):
    rows = [json.loads(x) for x in (mode_dir / "events.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    samples = [r for r in rows if r.get("event") == "actor_sample"]
    errors = [r for r in rows if r.get("event") == "sample_error"]
    commands = [r for r in rows if r.get("event") == "gc_command"]
    sprint = next((timestamp(r["wall_time"]) for r in rows
                   if r.get("event") == "rosout" and "SPRINT_START" in r.get("message", "")), None)
    first_lower = next((r for r in samples if r.get("reported_count", 3) < 3), None)
    intervals = [(timestamp(b["wall_time"]) - timestamp(a["wall_time"])).total_seconds()
                 for a, b in zip(samples, samples[1:])]
    trial_file = mode_dir / "trial_dir.txt"
    trial = Path(trial_file.read_text(encoding="utf-8").strip()) if trial_file.exists() else None
    final_phases = {}
    if trial and (trial / "scene_snapshots.jsonl").exists():
        final_phases = {r["phase"]: r["reported_count"] for r in (
            json.loads(x) for x in (trial / "scene_snapshots.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip())}
    return {
        "mode": mode_dir.name, "trial_dir": str(trial) if trial else "",
        "sample_count": len(samples), "sample_error_count": len(errors),
        "median_sample_interval_seconds": round(statistics.median(intervals), 3) if intervals else None,
        "sprint_start": iso(sprint), "gc_command_count": len(commands),
        "gc_command_times": [r["wall_time"] for r in commands],
        "first_count_below_three": iso(timestamp(first_lower["wall_time"])) if first_lower else "",
        "first_count_below_three_value": first_lower["reported_count"] if first_lower else None,
        "seconds_from_sprint_to_first_lower": round((timestamp(first_lower["wall_time"]) - sprint).total_seconds(), 3)
            if first_lower and sprint else None,
        "first_count": samples[0]["reported_count"] if samples else None,
        "last_count": samples[-1]["reported_count"] if samples else None,
        "formal_snapshots": final_phases,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("comparison_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = [summarize(path) for path in sorted(args.comparison_dir.iterdir())
              if path.is_dir() and (path / "events.jsonl").exists()]
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
