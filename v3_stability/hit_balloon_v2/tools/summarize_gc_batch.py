#!/usr/bin/env python3
"""Summarize fresh-scene trials measured with continuous UE garbage collection."""

import csv
import json
from pathlib import Path
import sys


FIELDS = ["round", "color", "trial_dir", "valid", "runner_rc", "before_count",
          "settled_count", "gc_samples", "gc_commands", "gc_errors",
          "gc_first_count", "gc_last_count", "gc_transitions",
          "boundary_violations", "bt_success", "mission_success"]


def observer(path):
    content = path.read_text(encoding="utf-8", errors="replace")
    first = content.index("{")
    value, _ = json.JSONDecoder().raw_decode(content[first:])
    return value


def main():
    batch = Path(sys.argv[1])
    rows = []
    with (batch / "trials.csv").open(newline="", encoding="utf-8") as stream:
        trials = list(csv.DictReader(stream))
    for trial in trials:
        folder = Path(trial["trial_dir"])
        events = [json.loads(line) for line in
                  (folder / "gc_continuous/events.jsonl").open(encoding="utf-8")]
        samples = [event for event in events if event.get("event") == "actor_sample"]
        transitions = []
        for previous, current in zip(samples, samples[1:]):
            if previous["reported_count"] != current["reported_count"]:
                transitions.append(f'{previous["reported_count"]}->{current["reported_count"]}'
                                   f'@{current["wall_time"]}')
        outcome = observer(folder / "observer.out")
        rows.append({
            **{key: trial[key] for key in ("round", "color", "trial_dir", "valid",
                                             "runner_rc", "before_count", "settled_count")},
            "gc_samples": len(samples),
            "gc_commands": sum(event.get("event") == "gc_command" for event in events),
            "gc_errors": sum(event.get("event") == "sample_error" for event in events),
            "gc_first_count": samples[0]["reported_count"] if samples else "",
            "gc_last_count": samples[-1]["reported_count"] if samples else "",
            "gc_transitions": "|".join(transitions),
            "boundary_violations": outcome["boundary_violation_count"],
            "bt_success": outcome["bt_success"],
            "mission_success": outcome["mission_success"],
        })
    output = batch / "gc_summary.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(output)
    for row in rows:
        print(f'{row["round"]} {row["color"]}: '
              f'{row["gc_first_count"]}->{row["gc_last_count"]}, '
              f'errors={row["gc_errors"]}, boundary={row["boundary_violations"]}')


if __name__ == "__main__":
    main()
