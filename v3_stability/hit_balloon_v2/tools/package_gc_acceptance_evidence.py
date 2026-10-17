#!/usr/bin/env python3
"""Archive raw continuous-GC evidence and nearby real frames for a batch.

This selects images by timestamps only. It makes no hit or color inference.
Usage: python3 package_gc_acceptance_evidence.py BATCH OUTPUT.tar.gz
"""

import csv
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import tarfile


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def add_file(archive, path, name):
    if path.is_file():
        archive.add(path, arcname=name)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    batch, output = (Path(arg) for arg in sys.argv[1:])
    with (batch / "trials.csv").open(newline="", encoding="utf-8") as source:
        trials = list(csv.DictReader(source))
    manifest = []
    with tarfile.open(output, "w:gz") as archive:
        for name in ("trials.csv", "progress.log", "exit_code", "gc_summary.csv"):
            add_file(archive, batch / name, name)
        for row in trials:
            trial = Path(row["trial_dir"])
            label = f"r{row['round']}_{row['color']}_a{row['attempt']}"
            events_path = trial / "gc_continuous/events.jsonl"
            if not events_path.is_file():
                manifest.append({"label": label, "trial_dir": str(trial),
                                 "error": "missing gc events"})
                continue
            events = [json.loads(line) for line in events_path.read_text(
                encoding="utf-8").splitlines() if line.strip()]
            samples = [event for event in events if event.get("event") == "actor_sample"]
            transitions = []
            for before, after in zip(samples, samples[1:]):
                if before["reported_count"] != after["reported_count"]:
                    transitions.append({
                        "from": before["reported_count"],
                        "to": after["reported_count"],
                        "previous_time": before["wall_time"],
                        "current_time": after["wall_time"],
                        "removed_actor_ids": sorted(set(before["actor_ids"]) -
                                                    set(after["actor_ids"])),
                    })
            for name in ("scene_snapshots.jsonl", "observer.out", "mission_once.out",
                         "judgement.json", "real_frames/frames.jsonl",
                         "gc_continuous/events.jsonl"):
                add_file(archive, trial / name, f"{label}/{name}")
            telemetry = list(trial.glob("*telemetry.jsonl"))
            if len(telemetry) == 1:
                with telemetry[0].open(encoding="utf-8") as source:
                    rosout = "".join(line for line in source if
                                     json.loads(line).get("event") == "rosout")
                add_bytes(archive, f"{label}/rosout_events.jsonl",
                          rosout.encode("utf-8"))
            frame_path = trial / "real_frames/frames.jsonl"
            selected = set()
            if frame_path.is_file():
                frames = [json.loads(line) for line in frame_path.read_text(
                    encoding="utf-8").splitlines() if line.strip()]
                for event in transitions:
                    moment = timestamp(event["current_time"])
                    for frame in frames:
                        if -12 <= timestamp(frame["wall_time"]) - moment <= 5:
                            selected.add(frame["image"])
                for name in selected:
                    add_file(archive, trial / "real_frames" / name,
                             f"{label}/real_frames/{name}")
            manifest.append({"label": label, "trial_dir": str(trial),
                             "gc_samples": len(samples), "transitions": transitions,
                             "selected_frames": sorted(selected),
                             "full_frame_index": str(frame_path),
                             "telemetry": [str(path) for path in telemetry]})
        add_bytes(archive, "manifest.json", (json.dumps(
            manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(output, output.stat().st_size)


if __name__ == "__main__":
    main()
