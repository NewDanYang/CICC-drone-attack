#!/usr/bin/env python3
"""Conservative, color-independent hit adjudication from one formal trial.

The normal TCEI observer's ``hit_balloon_status`` records VisualServo's sprint
completion, not balloon destruction.  This program requires a separate scene
event to return true/false.  Missing or uncalibrated scene evidence is unknown.

Optional ``scene_events.jsonl`` rows are produced by an independent simulator
observer, not by the behavior tree::

    {"wall_time":"...+00:00", "event":"balloon_destroyed", "color":"red",
     "source":"simulator_actor", "actor_id":"..."}
    {"wall_time":"...+00:00", "event":"balloon_alive", "color":"red",
     "source":"simulator_actor", "actor_id":"..."}

``balloon_alive`` must be an authoritative post-trial query of a live actor.
Detector absence, a completed sprint, and BT SUCCESS never prove a hit.
``scene_snapshots.jsonl`` from scene_snapshot.py reports actor-set changes.
Actor IDs are mapped to colors only by per-UE-instance calibration in
actor_scene_calibrations.json. A single disappearance is credited only when
the calibration covers that exact instance and target pixels were logged.
Actor color is not a native UE property in these snapshots; inspect the
calibration evidence and limits.
An unchanged actor list is not called a miss until a snapshot at least 120 s
after trial end, because UE garbage collection can delay object removal.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import re

COLORS = {"red", "purple", "blue"}
SPRINT_START = re.compile(r"-> SPRINT!")
SPRINT_END = re.compile(r"Sprint completed")
TRACKING = re.compile(r"\[TargetTracker\]: Tracking at pixel")
BT_TARGET = re.compile(r'<TargetTracker object_name="([a-z]+_balloon)"')
CALIBRATION = Path(__file__).with_name("actor_scene_calibrations.json")


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def trial_color(path):
    env = path / "trial.env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("color="):
                color = line.split("=", 1)[1].strip()
                if color in COLORS:
                    return color
    match = re.search(r"(?:^|_)(red|purple|blue)(?:_|$)", path.name)
    return match.group(1) if match else None


def read_telemetry(path):
    candidates = sorted(path.glob("*telemetry.jsonl"))
    if len(candidates) != 1:
        return {"path": None, "trial_start": None, "trial_end": None,
                "sprint_starts": [], "sprint_ends": [],
                "tracked_pixels": 0, "bt_targets": [],
                "error": f"expected one telemetry JSONL, found {len(candidates)}"}
    starts, ends = [], []
    tracked_pixels = 0
    bt_targets = set()
    trial_start = trial_end = None
    with candidates[0].open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("event") == "v21_run_start":
                trial_start = row["wall_time"]
            if row.get("event") == "v21_summary":
                trial_end = row["wall_time"]
            if row.get("event") != "rosout":
                continue
            message = row.get("message", "")
            if TRACKING.search(message):
                tracked_pixels += 1
            bt_targets.update(BT_TARGET.findall(message))
            if SPRINT_START.search(message):
                starts.append(row["wall_time"])
            if SPRINT_END.search(message):
                ends.append(row["wall_time"])
    return {"path": str(candidates[0]), "trial_start": trial_start,
            "trial_end": trial_end, "sprint_starts": starts,
            "sprint_ends": ends, "tracked_pixels": tracked_pixels,
            "bt_targets": sorted(bt_targets), "error": None}


def read_scene_events(path):
    source = path / "scene_events.jsonl"
    if not source.exists():
        return [], None
    rows = []
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") not in {"balloon_destroyed", "balloon_alive"}:
            continue
        if row.get("color") not in COLORS or row.get("source") != "simulator_actor":
            raise ValueError(f"invalid scene evidence at {source}:{number}")
        row["_line"] = number
        timestamp(row["wall_time"])
        rows.append(row)
    return rows, str(source)


def read_snapshots(path):
    source = path / "scene_snapshots.jsonl"
    if not source.exists():
        return None
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    before = [row for row in rows if row.get("phase") == "before"]
    after = [row for row in rows if row.get("phase") in {"after", "late", "settled"}]
    if len(before) != 1 or not after:
        return {"path": str(source), "error": "expected one before and at least one after snapshot"}
    a = before[0]
    after.sort(key=lambda row: timestamp(row["wall_time"]))
    b = after[-1]
    if a.get("source") != "ue_console_obj_list" or b.get("source") != "ue_console_obj_list":
        return {"path": str(source), "error": "unrecognized snapshot source"}
    if any(a.get("sim_pid") != row.get("sim_pid")
           or a.get("log_inode") != row.get("log_inode") for row in after):
        return {"path": str(source), "error": "simulator changed between snapshots"}
    first, last = set(a["actor_ids"]), set(b["actor_ids"])
    if (len(first) != a["reported_count"]
            or any(len(set(row["actor_ids"])) != row["reported_count"] for row in after)):
        return {"path": str(source), "error": "actor count disagrees with listed IDs"}
    if timestamp(a["wall_time"]) >= timestamp(b["wall_time"]):
        return {"path": str(source), "error": "snapshot order invalid"}
    return {"path": str(source), "error": None, "sim_pid": a["sim_pid"],
            "log_inode": a["log_inode"],
            "before": sorted(first), "after": sorted(last),
            "removed": sorted(first - last), "added": sorted(last - first),
            "before_time": a["wall_time"], "after_time": b["wall_time"],
            "after_phase": b["phase"], "after_observations": [
                {"phase": row["phase"], "wall_time": row["wall_time"],
                 "actor_ids": row["actor_ids"]} for row in after]}


def infer_actor_colors(path, snapshots):
    """Use only a color mapping documented for this exact UE instance."""
    if not snapshots or snapshots.get("error"):
        return {"error": "no valid same-instance scene snapshots"}
    if not CALIBRATION.exists():
        return {"error": f"scene calibration missing: {CALIBRATION}"}
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    candidates = []
    for source in path.parent.glob("*/scene_snapshots.jsonl"):
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("phase") == "before"
                    and row.get("sim_pid") == snapshots["sim_pid"]
                    and row.get("log_inode") == snapshots["log_inode"]
                    and row.get("reported_count") == 3
                    and len(set(row.get("actor_ids", []))) == 3):
                candidates.append((timestamp(row["wall_time"]), sorted(row["actor_ids"]), str(source)))
    if not candidates:
        return {"error": "full three-actor roster for this UE process unavailable"}
    candidates.sort(key=lambda item: item[0])
    roster = candidates[0][1]
    if any(item[1] != roster for item in candidates):
        return {"error": "inconsistent full rosters within one UE process"}
    entries = [entry for entry in calibration.get("scenes", [])
               if entry.get("sim_pid") == snapshots["sim_pid"]
               and entry.get("roster") == roster]
    if len(entries) != 1:
        return {"error": "no unique color calibration for this UE instance and roster",
                "roster": roster, "sim_pid": snapshots["sim_pid"]}
    entry = entries[0]
    if (set(entry.get("actor_to_color", {})) != set(roster)
            or set(entry["actor_to_color"].values()) != COLORS):
        return {"error": "incomplete or invalid scene color calibration"}
    return {"error": None, "method": calibration["method"],
            "limitation": calibration["limitation"],
            "calibration_file": str(CALIBRATION),
            "roster_source": candidates[0][2],
            "roster": roster,
            "actor_to_color": entry["actor_to_color"],
            "calibration_evidence": entry.get("evidence", [])}


def judge(path):
    color = trial_color(path)
    if not color:
        raise ValueError("cannot determine trial color")
    telemetry = read_telemetry(path)
    scene, scene_path = read_scene_events(path)
    snapshots = read_snapshots(path)
    relevant = [row for row in scene if row["color"] == color]
    trial_start = timestamp(telemetry["trial_start"]) if telemetry["trial_start"] else None
    trial_end = timestamp(telemetry["trial_end"]) if telemetry["trial_end"] else None
    if snapshots and not snapshots["error"]:
        if not trial_start or not trial_end:
            snapshots["error"] = "trial bounds missing from telemetry"
        elif (timestamp(snapshots["before_time"]) > trial_start
              or timestamp(snapshots["after_time"]) < trial_end):
            snapshots["error"] = "snapshots do not bracket the trial"
    actor_colors = infer_actor_colors(path, snapshots)
    result = "unknown"
    reason = "no authoritative simulator actor evidence for the target color"
    decisive = None
    # The scene event must be after the trial begins. A balloon can also be
    # struck during approach, so do not require a completed sprint.
    for row in relevant:
        when = timestamp(row["wall_time"])
        if not trial_start or not trial_end or not (trial_start <= when <= trial_end):
            continue
        if row["event"] == "balloon_destroyed":
            result, reason, decisive = "true", "target actor destroyed", row
            break
    if result == "unknown" and trial_end:
        post = [row for row in relevant
                if row["event"] == "balloon_alive"
                and timestamp(row["wall_time"]) >= trial_end]
        if post:
            decisive = max(post, key=lambda row: timestamp(row["wall_time"]))
            result, reason = "false", "target actor confirmed alive after sprint"
    if result == "unknown" and snapshots and not snapshots["error"]:
        if actor_colors["error"]:
            reason = actor_colors["error"]
        elif telemetry["bt_targets"] != [color + "_balloon"]:
            reason = "generated BT did not exclusively select the requested color"
        elif snapshots["added"]:
            reason = "new balloon actor appeared during the trial"
        else:
            color_to_actor = {value: key for key, value in actor_colors["actor_to_color"].items()}
            target_actor = color_to_actor[color]
            settled_seconds = ((timestamp(snapshots["after_time"]) - trial_end)
                               .total_seconds() if trial_end else 0)
            removed = snapshots["removed"]
            if target_actor not in snapshots["before"]:
                reason = "requested color actor was absent before this trial"
            elif len(removed) > 1:
                reason = "multiple balloon actors removed; exclusive color hit unverified"
            elif len(removed) == 1 and removed[0] == target_actor:
                if telemetry["tracked_pixels"] > 0:
                    result = "true"
                    reason = ("calibrated actor for requested color removed during "
                              "single-color trial with target tracking; actor color inferred "
                              "from same-instance visual sequence")
                else:
                    reason = "target actor removed but no requested-color tracking pixels logged"
            elif settled_seconds >= 120:
                result = "false"
                if removed:
                    other_color = actor_colors["actor_to_color"].get(removed[0], "unknown")
                    reason = f"requested actor remained; inferred {other_color} actor removed instead"
                else:
                    reason = "requested color actor remained after at least 120 s of settling"
            else:
                reason = "requested actor remains; post-trial settling window is under 120 s"
    if decisive is not None:
        decisive = {key: value for key, value in decisive.items() if key != "_line"}
        decisive["line"] = next(row["_line"] for row in relevant
                                if row["wall_time"] == decisive["wall_time"]
                                and row["event"] == decisive["event"])
    return {"hit": result, "color": color, "reason": reason,
            "evidence": {"telemetry": telemetry["path"],
                         "scene_events": scene_path, "decisive_event": decisive,
                         "scene_snapshots": snapshots,
                         "actor_color_calibration": actor_colors,
                         "sprint_starts": telemetry["sprint_starts"],
                         "sprint_ends": telemetry["sprint_ends"],
                         "tracked_pixels": telemetry["tracked_pixels"],
                         "bt_targets": telemetry["bt_targets"],
                         "telemetry_error": telemetry["error"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    args = parser.parse_args()
    if not args.trial_dir.is_dir():
        parser.error("trial directory does not exist")
    print(json.dumps(judge(args.trial_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
