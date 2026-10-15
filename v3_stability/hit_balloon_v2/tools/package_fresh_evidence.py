#!/usr/bin/env python3
"""Preserve compact raw trial evidence and selected real frames locally."""
import argparse
import csv
import io
import json
from pathlib import Path
import tarfile


def add_text(archive, name, text):
    data = text.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def package(loop_dirs, output):
    manifest = []
    with tarfile.open(output, "w:gz") as archive:
        for batch_number, loop in enumerate(loop_dirs, 1):
            prefix = f"batch{batch_number}"
            for filename in ("trials.csv", "progress.log", "driver.log", "exit_code"):
                path = loop / filename
                if path.is_file():
                    archive.add(path, arcname=f"{prefix}/{filename}")
            with (loop / "trials.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                trial = Path(row["trial_dir"])
                label = f"{prefix}/r{row['round']}_{row['color']}_a{row['attempt']}"
                manifest.append({"label": label, "trial_dir": str(trial),
                                 "telemetry": [str(p) for p in trial.glob("*telemetry.jsonl")],
                                 "valid": row["valid"]})
                for filename in ("scene_snapshots.jsonl", "judgement.json", "observer.out",
                                 "mission_once.out", "color_frames.csv", "hit_timing_candidate.json",
                                 "real_frames/frames.jsonl"):
                    path = trial / filename
                    if path.is_file():
                        archive.add(path, arcname=f"{label}/{filename}")
                telemetry = list(trial.glob("*telemetry.jsonl"))
                if len(telemetry) == 1:
                    with telemetry[0].open(encoding="utf-8") as source:
                        lines = [line for line in source if json.loads(line).get("event") == "rosout"]
                    add_text(archive, f"{label}/rosout_events.jsonl", "".join(lines))
                frame_index = trial / "real_frames/frames.jsonl"
                candidate_file = trial / "hit_timing_candidate.json"
                if frame_index.is_file() and candidate_file.is_file():
                    frames = [json.loads(line)["image"] for line in frame_index.read_text(
                        encoding="utf-8").splitlines() if line.strip()]
                    candidate = json.loads(candidate_file.read_text(encoding="utf-8"))
                    selected = set()
                    for key in ("last_visible_image", "first_absent_image"):
                        name = candidate.get(key)
                        if name in frames:
                            index = frames.index(name)
                            selected.update(frames[max(0, index - 2):min(len(frames), index + 3)])
                    for name in sorted(selected):
                        path = trial / "real_frames" / name
                        if path.is_file():
                            archive.add(path, arcname=f"{label}/real_frames/{name}")
        add_text(archive, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("loop_dirs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.loop_dirs, args.output)
    print(args.output, args.output.stat().st_size)


if __name__ == "__main__":
    main()
