#!/usr/bin/env python3
"""Summarize continuous-GC samples without interpreting actor IDs as colors."""

import json
from pathlib import Path
import sys


def main():
    path = Path(sys.argv[1])
    events = [json.loads(line) for line in path.open(encoding="utf-8")]
    samples = [event for event in events if event.get("event") == "actor_sample"]
    transitions = []
    for previous, current in zip(samples, samples[1:]):
        if previous["reported_count"] != current["reported_count"]:
            transitions.append({
                "from": previous["reported_count"],
                "to": current["reported_count"],
                "previous_time": previous["wall_time"],
                "current_time": current["wall_time"],
                "removed_actor_ids": sorted(set(previous["actor_ids"]) - set(current["actor_ids"])),
            })
    print(json.dumps({
        "path": str(path),
        "gc_commands": sum(event.get("event") == "gc_command" for event in events),
        "samples": len(samples),
        "sample_errors": sum(event.get("event") == "sample_error" for event in events),
        "first_count": samples[0]["reported_count"] if samples else None,
        "last_count": samples[-1]["reported_count"] if samples else None,
        "transitions": transitions,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
