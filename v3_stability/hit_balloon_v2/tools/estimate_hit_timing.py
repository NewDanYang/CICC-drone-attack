#!/usr/bin/env python3
"""Bracket apparent target disappearance in real frames; never assert a UE hit."""
import argparse
import csv
import datetime as dt
import json
from pathlib import Path


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def rosout_times(trial):
    files = list(trial.glob("*telemetry.jsonl"))
    if len(files) != 1:
        return [], [], [], [], []
    starts, ends, boundaries, servo_starts, states = [], [], [], [], []
    for line in files[0].open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("event") != "rosout":
            continue
        message = row.get("message", "")
        t = timestamp(row["wall_time"])
        if "SPRINT_START" in message:
            starts.append(t)
        if "Visual Servo Started" in message:
            servo_starts.append(t)
        if "SPRINT_END" in message or "SPRINT_ABORT" in message:
            ends.append(t)
        if "DRONE OUT OF BOUNDARY" in message:
            boundaries.append(t)
        if "[VisualServo]: APPROACH -" in message:
            states.append((t, "approaching"))
        if "[VisualServo]: ALIGN -" in message or "[VisualServo]: Target lost" in message:
            states.append((t, "align_or_search"))
    return starts, ends, boundaries, servo_starts, states


def iso(value):
    return value.isoformat(timespec="milliseconds") if value else ""


def estimate(trial, color, minimum):
    color_csv = trial / "color_frames.csv"
    if not color_csv.exists():
        return {"status": "missing_color_frames"}
    with color_csv.open(newline="", encoding="utf-8") as stream:
        frames = list(csv.DictReader(stream))
    starts, ends, boundaries, servo_starts, states = rosout_times(trial)
    largest = [int(r["largest_blob_pixels"]) for r in frames]
    candidates = []
    for i in range(2, len(frames) - 1):
        if (largest[i - 1] >= minimum and largest[i] < minimum
                and largest[i + 1] < minimum
                and sum(x >= minimum for x in largest[max(0, i - 4):i]) >= 1):
            left, right = timestamp(frames[i - 1]["wall_time"]), timestamp(frames[i]["wall_time"])
            # A target may leave the image at another mission stage. Keep
            # candidates for inspection rather than treating any as a hit.
            candidates.append((i, left, right, max(largest[max(0, i - 4):i])))
    if not candidates:
        return {"status": "no_frame_transition", "frame_count": len(frames),
                "sprint_start": iso(starts[0]) if starts else "",
                "first_boundary": iso(boundaries[0]) if boundaries else ""}
    # Prefer the final disappearance that lasts to the end of capture. Earlier
    # losses can be ordinary occlusions followed by reacquisition.
    lasting = [item for item in candidates if max(largest[item[0]:]) < minimum]
    i, left, right, prior_max = (lasting[-1] if lasting else
                                 max(candidates, key=lambda item: item[3]))
    middle = left + (right - left) / 2
    previous_states = [state for t, state in states if t <= right]
    last_state = previous_states[-1] if previous_states else ""
    if starts:
        start = starts[0]
        end = ends[0] if ends else None
        if right < start:
            phase = last_state or "pre_sprint_servo"
        elif end and left > start and right < end:
            phase = "sprinting"
        elif left > start and end and left > end:
            phase = "after_sprint"
        else:
            phase = "phase_overlap"
    else:
        phase = last_state if servo_starts and left >= servo_starts[0] else "pre_servo_or_unknown"
    if boundaries:
        boundary = boundaries[0]
        order = "boundary_before_disappearance" if boundary < left else (
            "boundary_after_disappearance" if boundary > right else "same_sample_interval")
    else:
        order = "no_boundary_event"
    return {
        "status": "candidate_only", "color": color, "frame_count": len(frames),
        "last_visible": iso(left), "first_absent": iso(right),
        "midpoint_estimate": iso(middle),
        "half_interval_seconds": round((right - left).total_seconds() / 2, 3),
        "largest_blob_before": prior_max, "last_visible_blob": largest[i - 1],
        "first_absent_blob": largest[i], "phase_from_log": phase,
        "sprint_start": iso(starts[0]) if starts else "",
        "servo_start": iso(servo_starts[0]) if servo_starts else "",
        "sprint_end": iso(ends[0]) if ends else "",
        "first_boundary": iso(boundaries[0]) if boundaries else "",
        "boundary_order": order,
        "last_visible_image": frames[i - 1]["image"],
        "first_absent_image": frames[i]["image"],
        "candidate_count": len(candidates), "lasting_absence": bool(lasting),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("trial_dir", type=Path)
    p.add_argument("color", choices=["red", "purple", "blue"])
    p.add_argument("--minimum", type=int, default=1000)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = estimate(a.trial_dir, a.color, a.minimum)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if a.output:
        a.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
