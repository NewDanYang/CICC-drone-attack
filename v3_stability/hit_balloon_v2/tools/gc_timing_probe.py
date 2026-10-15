#!/usr/bin/env python3
"""Extra-trial UE actor sampling, optionally forcing GC after SPRINT_START."""
import argparse
import datetime as dt
import json
from pathlib import Path
import queue
import sys
import time

import rospy
from rosgraph_msgs.msg import Log

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene_snapshot import snapshot, SDK, LOG


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--mode", choices=["control", "gc", "continuous"], required=True)
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--duration", type=float, default=330.0)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    events = queue.Queue()
    rospy.init_node("balloon_gc_timing_probe", anonymous=True, disable_signals=True)

    def on_rosout(msg):
        if "SPRINT_START" in msg.msg or "Sprint completed" in msg.msg:
            events.put({"wall_time": utc_now(), "event": "rosout", "node": msg.name,
                        "message": msg.msg})

    rospy.Subscriber("/rosout", Log, on_rosout, queue_size=100)
    (args.output_dir / "ready").write_text(utc_now() + "\n", encoding="utf-8")
    start = time.monotonic()
    next_sample = start
    sprint_seen_at = None
    sprint_wall_time = None
    gc_schedule = [0.4, 1.4, 3.0, 5.0] if args.mode == "gc" else []
    gc_sent = 0
    with (args.output_dir / "events.jsonl").open("w", encoding="utf-8", buffering=1) as output:
        while (not rospy.is_shutdown() and time.monotonic() - start < args.duration
               and not (args.stop_file and args.stop_file.exists())):
            try:
                while True:
                    event = events.get_nowait()
                    output.write(json.dumps(event, ensure_ascii=False) + "\n")
                    if "SPRINT_START" in event["message"] and sprint_seen_at is None:
                        sprint_seen_at = time.monotonic()
                        sprint_wall_time = event["wall_time"]
            except queue.Empty:
                pass
            if (sprint_seen_at is not None and gc_sent < len(gc_schedule)
                    and time.monotonic() - sprint_seen_at >= gc_schedule[gc_sent]):
                sys.path.insert(0, SDK)
                from UE4CtrlAPI import UE4CtrlAPI
                sent_at = utc_now()
                log_offset = LOG.stat().st_size
                result = UE4CtrlAPI().sendUE4Cmd("obj gc")
                time.sleep(0.2)
                with LOG.open("rb") as log_file:
                    log_file.seek(log_offset)
                    log_excerpt = log_file.read(4096).decode("utf-8", "replace")
                output.write(json.dumps({"event": "gc_command", "wall_time": sent_at,
                                         "seconds_after_sprint_log": round((dt.datetime.fromisoformat(sent_at) -
                                                                              dt.datetime.fromisoformat(sprint_wall_time)).total_seconds(), 3),
                                         "command": "obj gc", "return_value": repr(result),
                                         "ue_log_excerpt": log_excerpt}) + "\n")
                gc_sent += 1
                next_sample = time.monotonic()
            if time.monotonic() >= next_sample:
                if args.mode == "continuous":
                    sys.path.insert(0, SDK)
                    from UE4CtrlAPI import UE4CtrlAPI
                    sent_at = utc_now()
                    log_offset = LOG.stat().st_size
                    result = UE4CtrlAPI().sendUE4Cmd("obj gc")
                    time.sleep(0.1)
                    with LOG.open("rb") as log_file:
                        log_file.seek(log_offset)
                        excerpt = log_file.read(4096).decode("utf-8", "replace")
                    output.write(json.dumps({"event": "gc_command", "wall_time": sent_at,
                                             "seconds_after_sprint_log": round((dt.datetime.fromisoformat(sent_at) -
                                                                                  dt.datetime.fromisoformat(sprint_wall_time)).total_seconds(), 3)
                                                 if sprint_wall_time else None,
                                             "command": "obj gc", "return_value": repr(result),
                                             "ue_log_excerpt": excerpt}) + "\n")
                try:
                    row = snapshot()
                    row["event"] = "actor_sample"
                    row["mode"] = args.mode
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                except Exception as exc:
                    output.write(json.dumps({"event": "sample_error", "wall_time": utc_now(),
                                             "error": repr(exc)}) + "\n")
                next_sample = time.monotonic() + args.interval
            time.sleep(0.1)
    (args.output_dir / "exit_code").write_text("0\n", encoding="ascii")


if __name__ == "__main__":
    main()
