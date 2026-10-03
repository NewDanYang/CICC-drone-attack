#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observer-only single-run baseline recorder for the TCEI ROS mission.

This program never publishes to /mission_command or any flight/control topic.
It optionally launches the official mission_once.py entry point with natural
language; that script performs the competition LLM -> /mission_command step.
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    import rospy
    from std_msgs.msg import String, Int32
    from rosgraph_msgs.msg import Log
except ImportError as exc:
    rospy = None
    String = Int32 = Log = None
    ROS_IMPORT_ERROR = exc

COLORS = ("red", "purple", "blue")
COLOR_ZH = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
CSV_FIELDS = [
    "run_id", "target_color", "start_time", "end_time", "total_time",
    "elapsed_time", "bt_success", "mission_success", "end_status",
    "takeoff_status", "cross_frame_status",
    "detect_aruco_status", "return_cross_frame_status", "hit_balloon_status",
    "land_status", "aruco_detect_time", "balloon_search_time",
    "failure_stage", "failure_reason", "safety_boundary_triggered",
    "boundary_first_time", "boundary_first_position", "boundary_violation_count",
    "boundary_recovered", "notes",
]

STAGE_FIELDS = (
    "takeoff_status", "cross_frame_status", "detect_aruco_status",
    "return_cross_frame_status", "hit_balloon_status", "land_status",
)

V21_PLANNING_FIELDS = [
    "run_id", "target_color", "config", "max_vel", "stage_name", "stage_index",
    "start_time", "end_time", "duration", "goal_xyz", "start_xyz", "end_xyz",
    "odom_source", "path_length", "odom_mean_speed", "odom_peak_speed",
    "planner_cmd_mean_speed", "planner_cmd_peak_speed",
    "setpoint_mean_speed", "setpoint_peak_speed", "final_position_error",
    "safety_boundary_triggered", "recovery_triggered", "recovery_completed",
    "recovery_duration",
    "replan_count", "collision", "mission_success", "bt_success",
    "total_mission_time", "notes",
]


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def epoch_iso(value):
    """Convert a replay/event epoch to the same UTC ISO form used by live runs."""
    return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).isoformat(timespec="milliseconds")


def parse_event_time(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def make_task(color):
    prefix = ''.join(chr(int(x, 16)) for x in (
        "98de 673a 8d77 98de ff0c 7136 540e 7a7f 8fc7 6846 ff0c "
        "518d 53bb 8bc6 522b 4e8c 7ef4 7801 ff0c 7136 540e 518d 7a7f "
        "56de 6846 ff0c 63a5 7740 53bb 6253 51fb"
    ).split())
    suffix = ''.join(chr(int(x, 16)) for x in (
        "6c14 7403 ff0c 5b8c 6210 540e 5c31 56de 5230 8d77 70b9 "
        "5e76 964d 843d ff1b"
    ).split())
    return prefix + COLOR_ZH[color] + suffix


class RunObserver:
    def __init__(self, args, log_path=None, run_id=None, record=True,
                 v21_log_path=None, v21_summary_path=None):
        self.args = args
        self.run_id = run_id or (dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6])
        self.target_color = args.color
        self.task_text = make_task(args.color)
        self.record = record
        self.monitor_start_wall = time.time()
        self.start_wall = None
        self.start_iso = ""
        self.end_wall = None
        self.end_iso = ""
        self.finish_reason = ""
        self.lock = threading.RLock()
        self.finished = threading.Event()
        self.terminal_result = ""
        self.bt_success = ""
        self.end_status = ""
        self.failure_reason = ""
        self.process = None
        self.command_seen = ""
        self.log_path = Path(log_path) if log_path else None
        self.log_fp = self.log_path.open("w", encoding="utf-8") if self.record and self.log_path else None
        self.v21_enabled = bool(getattr(args, "v21_telemetry", False))
        self.v21_log_path = Path(v21_log_path) if v21_log_path else None
        self.v21_summary_path = Path(v21_summary_path) if v21_summary_path else None
        self.v21_log_fp = None
        if self.v21_enabled and self.record and self.v21_log_path:
            self.v21_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.v21_log_fp = self.v21_log_path.open("w", encoding="utf-8")
        self.stages = {name: "" for name in STAGE_FIELDS}
        self.stage_times = {}
        self.aruco_start = None
        self.aruco_end = None
        self.balloon_start = None  # TargetTracker/VisualServo stage start only
        self.balloon_end = None
        self.frame_locator_seen = None
        self.frame_locator_success = None
        self.bt_xml_seen = False
        self.bt_plan_controls = []
        self.planning_open = []
        self.planning_runs = []
        self.notes = []
        self.last_fcu_state = ""
        self.setpoint_count = 0
        self.target_detections = 0
        self.safety_boundary_triggered = False
        self.boundary_first_time = ""
        self.boundary_first_position = ""
        self.boundary_violation_count = 0
        self.boundary_recovered = None
        self.last_check = None
        self.arrival_target = None
        self.arrival_best_distance = None
        self.arrival_last_progress = None
        self.stuck_detected = False
        self.stuck_reason = ""
        self.latest_odom = None
        self.latest_odom_by_topic = {}
        self.primary_odom_topic = "/rflysim/uav1/local/odom"
        self.recovery_triggered = False
        self.recovery_completed = False
        self.recovery_start = None
        self.recovery_end = None
        self.collision = ""
        self.v21_summary_written = False
        if self.v21_enabled:
            self._write_v21_event("v21_run_start", {
                "config": str(getattr(args, "v21_config", "")),
                "max_vel": str(getattr(args, "v21_max_vel", "")),
                "topics": [
                    "/mavros/local_position/odom",
                    "/rflysim/uav1/local/odom",
                    "/planning/pos_cmd",
                    "/mavros/setpoint_raw/local",
                ],
            })
        self._write_event("run_start", {"task_text": self.task_text, "target_color": self.target_color})

    def _write_event(self, event, data):
        if not self.record:
            return
        record = {"wall_time": now_iso(), "event": event, **data}
        with self.lock:
            if self.log_fp is None:
                return
            self.log_fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self.log_fp.flush()

    def _write_v21_event(self, event, data):
        if not self.v21_enabled:
            return
        record = {"wall_time": now_iso(), "event": event, **data}
        with self.lock:
            if self.v21_log_fp is None:
                return
            self.v21_log_fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self.v21_log_fp.flush()

    def _write_telemetry_event(self, event, data):
        self._write_event(event, data)
        self._write_v21_event(event, data)

    def add_note(self, text):
        with self.lock:
            if text not in self.notes:
                self.notes.append(text)
        self._write_event("note", {"text": text})

    def mark(self, field, status, source, when=None):
        with self.lock:
            if not self.stages.get(field):
                self.stages[field] = status
                self.stage_times[field] = when if when is not None else time.time()
        self._write_event("stage", {"field": field, "status": status, "source": source})

    def on_mission_command(self, msg, when=None, write_event=True):
        text = str(msg.data)
        timestamp = when if when is not None else time.time()
        first_command = not bool(self.command_seen)
        if first_command:
            self.start_wall = timestamp
            self.start_iso = epoch_iso(timestamp) if when is not None else now_iso()
            if write_event:
                self._write_event("mission_start", {
                "mission_start_time": self.start_iso,
                "source": "/mission_command",
                })
        self.command_seen = text
        if write_event:
            self._write_event("mission_command", {
                "data": text,
                "received_at": epoch_iso(timestamp) if when is not None else now_iso(),
                "is_first_command": first_command,
            })
        try:
            parsed = json.loads(text)
            commands = parsed.get("commands", parsed) if isinstance(parsed, dict) else parsed
            self.add_note("mission_command=" + json.dumps(commands, ensure_ascii=False))
        except Exception:
            self.add_note("mission_command received as text")

    def on_mission_result(self, msg, when=None, write_event=True):
        result = str(msg.data).strip()
        timestamp = when if when is not None else time.time()
        if write_event:
            self._write_event("mission_result", {"data": result})
        # Ignore a stale result that may be queued before this run's command.
        if not self.command_seen:
            self.add_note("ignored mission_result before mission_command: " + result)
            return
        if result == "BUSY":
            self.add_note("mission_result BUSY; observer continues waiting")
            return
        if result in ("SUCCESS", "FAILURE", "ABORTED") or result.startswith("ERROR:"):
            with self.lock:
                self.terminal_result = result
                self.bt_success = "true" if result == "SUCCESS" else "false"
                self.end_wall = timestamp
                self.end_iso = epoch_iso(timestamp) if when is not None else now_iso()
            if write_event:
                self._write_event("mission_end", {
                "mission_end_time": self.end_iso,
                "result": result,
                "source": "/mission_result",
                })
            self.finish("mission_result", when=timestamp)

    def on_rosout(self, msg):
        text = "[%s] %s" % (getattr(msg, "name", ""), getattr(msg, "msg", ""))
        level = getattr(msg, "level", 0)
        self._write_event("rosout", {"level": level, "name": getattr(msg, "name", ""), "message": getattr(msg, "msg", "")})
        if self.v21_enabled:
            self._write_v21_event("rosout", {
                "level": level,
                "name": getattr(msg, "name", ""),
                "message": getattr(msg, "msg", ""),
            })
        self._parse_log(text)

    @staticmethod
    def _xml_attr(tag, name):
        match = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag)
        return match.group(1) if match else ""

    def _capture_bt_xml(self, text, when):
        """Capture XML structure so stage labels come from the BT, not GoTo order."""
        start = text.find("<root")
        end = text.rfind("</root>")
        xml = text[start:end + len("</root>")] if start >= 0 and end >= start else text
        controls = []
        for tag in re.findall(r"<PlanningControl\b[^>]*/?>", xml, flags=re.IGNORECASE):
            goal = self._xml_attr(tag, "goal")
            offset = self._xml_attr(tag, "offset_z")
            if goal == "{frame_center}" and offset:
                kind = "frame_outbound"
            elif goal == "{frame_center}":
                kind = "frame_return"
            else:
                kind = "other"
            controls.append({"goal": goal, "offset_z": offset, "kind": kind})
        self.bt_xml_seen = True
        self.bt_plan_controls = controls
        self._write_event("bt_xml", {
            "planning_controls": controls,
            "has_frame_locator": bool(re.search(r"<TargetLocator\b[^>]*object_name=\"square_frame\"", xml, re.I)),
            "captured_at": epoch_iso(when) if when is not None else now_iso(),
        })

    def _parse_position(self, text):
        match = re.search(r"at \(([-+0-9.eE]+),\s*([-+0-9.eE]+),\s*([-+0-9.eE]+)\)", text)
        if not match:
            return ""
        return "(%s, %s, %s)" % match.groups()

    @staticmethod
    def _vector3(value):
        if value is None:
            return None
        try:
            return {
                "x": float(getattr(value, "x")),
                "y": float(getattr(value, "y")),
                "z": float(getattr(value, "z")),
            }
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _speed(vector):
        if not vector:
            return None
        return math.sqrt(vector["x"] ** 2 + vector["y"] ** 2 + vector["z"] ** 2)

    @staticmethod
    def _stamp_seconds(msg):
        header = getattr(msg, "header", None)
        stamp = getattr(header, "stamp", None) if header else None
        try:
            value = stamp.to_sec()
            return float(value) if value else None
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_xyz(text):
        if not text:
            return None
        values = re.findall(r"[-+0-9.eE]+", str(text))
        if len(values) != 3:
            return None
        try:
            return tuple(float(value) for value in values)
        except ValueError:
            return None

    @staticmethod
    def _format_xyz(value):
        if value is None:
            return ""
        return "(%.4f, %.4f, %.4f)" % tuple(value)

    @staticmethod
    def _mean(values):
        return sum(values) / len(values) if values else None

    @staticmethod
    def _stage_name(control, index):
        if control:
            kind = control.get("kind")
            if kind == "frame_outbound":
                return "first_cross_frame_planning"
            if kind == "frame_return":
                return "return_cross_frame_planning"
            if kind == "other":
                return "balloon_positioning_planning"
        return "planning_control_%d" % (index + 1)

    def _active_planning(self):
        return self.planning_open[-1] if self.planning_open else None

    def _record_odom_metric(self, sample):
        if sample.get("topic") != self.primary_odom_topic:
            return
        stage = self._active_planning()
        if stage is None or sample["when"] < stage["start"]:
            return
        previous = stage.get("last_odom")
        if previous is not None and sample["when"] >= previous["when"]:
            stage["path_length"] += math.dist(sample["position"], previous["position"])
        elif previous is None and stage.get("start_xyz") is not None:
            # Include the short segment between the PlanningControl event and
            # the first odometry sample in the stage path estimate.
            stage["path_length"] += math.dist(sample["position"], stage["start_xyz"])
        if sample.get("speed") is not None:
            stage["odom_speeds"].append(sample["speed"])
        stage["last_odom"] = sample

    def _record_command_metric(self, stream_name, sample):
        stage = self._active_planning()
        if stage is None or sample["when"] < stage["start"]:
            return
        speed = sample.get("speed")
        if speed is not None:
            stage[stream_name].append(speed)

    def on_odom(self, topic, msg):
        timestamp = time.time()
        pose = getattr(getattr(msg, "pose", None), "pose", None)
        twist = getattr(getattr(msg, "twist", None), "twist", None)
        position = self._vector3(getattr(pose, "position", None))
        velocity = self._vector3(getattr(twist, "linear", None))
        if position is None or velocity is None:
            return
        sample = {
            "topic": topic,
            "sample_wall_time": epoch_iso(timestamp),
            "header_stamp": self._stamp_seconds(msg),
            "position": position,
            "velocity": velocity,
            "speed": self._speed(velocity),
        }
        with self.lock:
            state = {"when": timestamp, "topic": topic,
                     "position": tuple(position.values()),
                     "velocity": velocity, "speed": sample["speed"]}
            self.latest_odom_by_topic[topic] = state
            if topic == self.primary_odom_topic:
                self.latest_odom = state
            self._record_odom_metric(state)
        self._write_telemetry_event("odom_sample", sample)

    def _planner_sample(self, msg):
        timestamp = time.time()
        position = self._vector3(getattr(msg, "position", None))
        velocity = self._vector3(getattr(msg, "velocity", None))
        acceleration = self._vector3(getattr(msg, "acceleration", None))
        return {
            "topic": "/planning/pos_cmd",
            "when": timestamp,
            "sample_wall_time": epoch_iso(timestamp),
            "header_stamp": self._stamp_seconds(msg),
            "position": position,
            "velocity": velocity,
            "speed": self._speed(velocity),
            "acceleration": acceleration,
            "yaw": getattr(msg, "yaw", None),
            "yaw_dot": getattr(msg, "yaw_dot", None),
        }

    def _setpoint_sample(self, msg):
        timestamp = time.time()
        position = self._vector3(getattr(msg, "position", None))
        velocity = self._vector3(getattr(msg, "velocity", None))
        acceleration = self._vector3(getattr(msg, "acceleration_or_force", None))
        return {
            "topic": "/mavros/setpoint_raw/local",
            "when": timestamp,
            "sample_wall_time": epoch_iso(timestamp),
            "header_stamp": self._stamp_seconds(msg),
            "coordinate_frame": getattr(msg, "coordinate_frame", None),
            "type_mask": getattr(msg, "type_mask", None),
            "position": position,
            "velocity": velocity,
            "speed": self._speed(velocity),
            "acceleration_or_force": acceleration,
            "yaw": getattr(msg, "yaw", None),
            "yaw_rate": getattr(msg, "yaw_rate", None),
        }

    def _parse_check_arrival(self, text, when):
        match = re.search(
            r"odom=\(([-+0-9.eE]+),\s*([-+0-9.eE]+),\s*([-+0-9.eE]+)\).*?"
            r"target=\(([-+0-9.eE]+),\s*([-+0-9.eE]+),\s*([-+0-9.eE]+)\).*?"
            r"dist=([-+0-9.eE]+)", text)
        if not match:
            return
        values = [float(x) for x in match.groups()]
        position = tuple(values[0:3])
        target = tuple(values[3:6])
        distance = values[6]
        current = {"when": when if when is not None else time.time(), "position": position,
                   "target": target, "distance": distance}
        previous = self.last_check
        self.last_check = current
        if previous is None or previous["target"] != target:
            self.arrival_target = target
            self.arrival_best_distance = distance
            self.arrival_last_progress = current["when"]
            return
        if self.arrival_best_distance is None or distance < self.arrival_best_distance - 0.08:
            self.arrival_best_distance = distance
            self.arrival_last_progress = current["when"]
        elapsed = current["when"] - (self.arrival_last_progress or current["when"])
        if elapsed >= 20.0 and distance > 0.15:
            if not self.stuck_detected:
                self.stuck_detected = True
                self.stuck_reason = "checkArrival made no progress for %.1fs at target %s" % (elapsed, target)
                self.add_note(self.stuck_reason)

    def _planning_start(self, text, when):
        match = re.search(r"Planning navigation start ->\s*\(([^)]*)\)", text)
        start = when if when is not None else time.time()
        control_index = len(self.planning_runs) + len(self.planning_open)
        control = self.bt_plan_controls[control_index] if control_index < len(self.bt_plan_controls) else None
        goal_text = match.group(1) if match else ""
        self.planning_open.append({
            "when": start,
            "start": start,
            "index": control_index,
            "goal": goal_text,
            "goal_xyz": self._parse_xyz(goal_text),
            "stage_name": self._stage_name(control, control_index),
            "start_xyz": (
                self.latest_odom["position"] if self.latest_odom else
                self.latest_odom_by_topic.get("/mavros/local_position/odom", {}).get("position")
            ),
            "odom_source": self.primary_odom_topic,
            "path_length": 0.0,
            "odom_speeds": [],
            "planner_speeds": [],
            "setpoint_speeds": [],
            "replan_count": 0,
            "last_odom": None,
        })

    def _finalize_planning(self, stage, end, success):
        last_odom = stage.get("last_odom")
        start_xyz = stage.get("start_xyz")
        end_xyz = last_odom["position"] if last_odom else None
        goal_xyz = stage.get("goal_xyz")
        final_error = math.dist(end_xyz, goal_xyz) if end_xyz and goal_xyz else None
        return {
            "index": stage["index"],
            "stage_name": stage["stage_name"],
            "start": stage["start"],
            "end": end,
            "duration": max(0.0, end - stage["start"]),
            "goal_xyz": goal_xyz,
            "start_xyz": start_xyz,
            "end_xyz": end_xyz,
            "path_length": stage["path_length"],
            "odom_mean_speed": self._mean(stage["odom_speeds"]),
            "odom_peak_speed": max(stage["odom_speeds"], default=None),
            "planner_cmd_mean_speed": self._mean(stage["planner_speeds"]),
            "planner_cmd_peak_speed": max(stage["planner_speeds"], default=None),
            "setpoint_mean_speed": self._mean(stage["setpoint_speeds"]),
            "setpoint_peak_speed": max(stage["setpoint_speeds"], default=None),
            "final_position_error": final_error,
            "success": success,
            "replan_count": stage["replan_count"],
        }

    def _planning_complete(self, text, when, success=True):
        if not self.planning_open:
            return
        started = self.planning_open.pop(0)
        completed_at = when if when is not None else time.time()
        control_index = started["index"]
        control = self.bt_plan_controls[control_index] if control_index < len(self.bt_plan_controls) else None
        run = self._finalize_planning(started, completed_at, success)
        run.update({"goal": started["goal"], "control": control})
        self.planning_runs.append(run)
        if self.v21_enabled:
            self._write_telemetry_event("planning_stage", self._planning_event(run))
        if not success or control is None:
            return
        if control["kind"] == "frame_outbound" and self.frame_locator_success is not None:
            self.mark("cross_frame_status", "success", text, completed_at)
        elif control["kind"] == "frame_return" and self.stages["detect_aruco_status"] == "success":
            self.mark("return_cross_frame_status", "success", text, completed_at)

    def _finalize_open_planning(self, end):
        """Record a partial PlanningControl when a run ends without completion."""
        while self.planning_open:
            started = self.planning_open.pop(0)
            control = (
                self.bt_plan_controls[started["index"]]
                if started["index"] < len(self.bt_plan_controls) else None
            )
            run = self._finalize_planning(started, end, success=False)
            run.update({"goal": started["goal"], "control": control, "incomplete": True})
            self.planning_runs.append(run)
            if self.v21_enabled:
                self._write_telemetry_event("planning_stage_incomplete", self._planning_event(run))

    def _planning_event(self, run):
        return {
            "stage_name": run["stage_name"],
            "stage_index": run["index"],
            "start_time": epoch_iso(run["start"]),
            "end_time": epoch_iso(run["end"]),
            "duration": run["duration"],
            "goal_xyz": run["goal_xyz"],
            "start_xyz": run["start_xyz"],
            "end_xyz": run["end_xyz"],
            "path_length": run["path_length"],
            "odom_mean_speed": run["odom_mean_speed"],
            "odom_peak_speed": run["odom_peak_speed"],
            "planner_cmd_mean_speed": run["planner_cmd_mean_speed"],
            "planner_cmd_peak_speed": run["planner_cmd_peak_speed"],
            "setpoint_mean_speed": run["setpoint_mean_speed"],
            "setpoint_peak_speed": run["setpoint_peak_speed"],
            "final_position_error": run["final_position_error"],
            "success": run["success"],
            "replan_count": run["replan_count"],
        }

    def _parse_log(self, text, when=None):
        low = text.lower()
        timestamp = when if when is not None else time.time()

        # The XML is evidence about the control graph, never a stage result.
        if "generated bt xml" in low:
            self._capture_bt_xml(text, timestamp)
            return

        # Safety messages are kept independently of BT success.
        if "drone out of boundary" in low:
            self.safety_boundary_triggered = True
            self.boundary_violation_count += 1
            self.boundary_recovered = False
            position = self._parse_position(text)
            if not self.boundary_first_time:
                self.boundary_first_time = epoch_iso(timestamp)
                self.boundary_first_position = position
            self._write_event("safety_boundary", {
                "time": epoch_iso(timestamp), "position": position,
                "count": self.boundary_violation_count,
            })
        if "hover lock" in low:
            self._write_event("safety_hover_lock", {"time": epoch_iso(timestamp), "message": text})
        if "drone returned to safe area" in low:
            self.boundary_recovered = True
            self._write_event("safety_recovered", {"time": epoch_iso(timestamp)})
        if "safetyrecovery" in low and "enter" in low:
            self.recovery_triggered = True
            self.recovery_start = self.recovery_start or timestamp
        if "safetyrecovery" in low and "complete" in low:
            self.recovery_completed = True
            self.recovery_end = timestamp

        if (
            "collision detected" in low
            or "collision!" in low
            or "penetrat" in low
            or "crash" in low
        ):
            self.collision = "true"
            self._write_event("collision_evidence", {"time": epoch_iso(timestamp), "message": text})

        if self._active_planning() is not None and "replan" in low:
            self._active_planning()["replan_count"] += 1

        if "checkarrival" in low:
            self._parse_check_arrival(text, timestamp)

        # Takeoff and landing have explicit node names and completion messages.
        if "takeoff completed" in low:
            self.mark("takeoff_status", "success", text, timestamp)
        elif ("[takeoff" in low and ("failure" in low or "failed" in low)):
            self.mark("takeoff_status", "failure", text, timestamp)
        if "landed and disarmed" in low:
            self.mark("land_status", "success", text, timestamp)
        elif "[land" in low and ("failure" in low or "failed" in low):
            self.mark("land_status", "failure", text, timestamp)

        if "detecting target: square_frame" in low:
            self.frame_locator_seen = self.frame_locator_seen or timestamp
            self.stage_times.setdefault("frame_locator_start", timestamp)
        if "target located" in low and "success" in low and self.frame_locator_seen is not None:
            self.frame_locator_success = self.frame_locator_success or timestamp
            self._write_event("frame_locator_success", {"time": epoch_iso(timestamp)})

        if "[arucodetectnode] >>> detection enabled" in low:
            self.aruco_start = self.aruco_start or timestamp
            self.stage_times.setdefault("detect_aruco_start", self.aruco_start)
        if "aruco id detected" in low:
            self.aruco_end = self.aruco_end or timestamp
            self.mark("detect_aruco_status", "success", text, timestamp)
        elif (
            "aruco" in low
            and ("timeout" in low or "failure" in low)
        ):
            self.mark("detect_aruco_status", "failure", text, timestamp)

        if "planning navigation start ->" in low:
            self._planning_start(text, timestamp)
        if "planning navigation completed" in low:
            self._planning_complete(text, timestamp, success=True)
        elif "planning navigation" in low and ("failure" in low or "failed" in low):
            self._planning_complete(text, timestamp, success=False)

        target = "red_balloon" if "red_balloon" in low else "purple_balloon" if "purple_balloon" in low else "blue_balloon" if "blue_balloon" in low else None
        if "detecting target:" in low and "balloon" in low:
            if target and target != self.target_color + "_balloon":
                self.add_note("behavior tree target differs from requested color: " + target)
            if target == self.target_color + "_balloon":
                self.balloon_start = self.balloon_start or timestamp
            if self.balloon_start is not None:
                self.stage_times.setdefault("balloon_start", self.balloon_start)
        if "visual servo started" in low and self.balloon_start is None:
            self.balloon_start = timestamp
            self.stage_times.setdefault("balloon_start", timestamp)
        if "sprint completed" in low and "success" in low:
            self.balloon_end = self.balloon_end or timestamp
            self.mark("hit_balloon_status", "success", text, timestamp)
        elif ("visual servo" in low or "[targettracker" in low) and ("failure" in low or "failed" in low):
            self.mark("hit_balloon_status", "failure", text, timestamp)

    def on_aruco_id(self, msg, when=None, write_event=True):
        timestamp = when if when is not None else time.time()
        self.aruco_end = self.aruco_end or timestamp
        if write_event:
            self._write_event("aruco_detected_id", {"id": int(msg.data)})
        self.mark("detect_aruco_status", "success", "topic /aruco/detected_id", timestamp)

    def on_objects(self, msg, when=None):
        found = []
        for obj in getattr(msg, "objects", []):
            name = str(getattr(obj, "class_name", ""))
            if name in ("red_balloon", "purple_balloon", "blue_balloon"):
                found.append(name)
        if found:
            self.target_detections += len(found)
            self._write_event("objects_target", {"classes": found})

    def on_aruco_id_value(self, value, when=None):
        class Msg:
            data = value
        self.on_aruco_id(Msg(), when=when, write_event=False)

    def replay_record(self, record):
        """Replay only evidence events; old derived stage events are deliberately ignored."""
        event = record.get("event")
        when = parse_event_time(record.get("wall_time"))
        if event == "mission_command":
            class Msg:
                data = record.get("data", "")
            self.on_mission_command(Msg(), when=when, write_event=False)
        elif event == "mission_result":
            class Msg:
                data = record.get("data", "")
            self.on_mission_result(Msg(), when=when, write_event=False)
        elif event == "rosout":
            text = "[%s] %s" % (record.get("name", ""), record.get("message", ""))
            self._parse_log(text, when)
        elif event == "aruco_detected_id":
            self.on_aruco_id_value(record.get("id", 0), when)
        elif event == "objects_target":
            self.target_detections += len(record.get("classes", []))

    def on_setpoint(self, msg):
        self.setpoint_count += 1
        sample = self._setpoint_sample(msg)
        with self.lock:
            self._record_command_metric("setpoint_speeds", sample)
        if self.v21_enabled:
            self._write_telemetry_event("setpoint_sample", sample)

    def on_state(self, msg):
        state = "connected=%s armed=%s mode=%s" % (
            getattr(msg, "connected", ""), getattr(msg, "armed", ""), getattr(msg, "mode", ""))
        if state != self.last_fcu_state:
            self.last_fcu_state = state
            self._write_event("mavros_state", {"state": state})

    def on_generic(self, topic, msg):
        if topic == "/planning/pos_cmd" and self.v21_enabled:
            sample = self._planner_sample(msg)
            with self.lock:
                self._record_command_metric("planner_speeds", sample)
            self._write_telemetry_event("planner_sample", sample)
        else:
            self._write_event("topic_sample", {"topic": topic, "type": type(msg).__name__})

    def _v21_row(self, run, mission):
        def number(value):
            return "" if value is None else "%.6f" % value

        def xyz(value):
            return self._format_xyz(value)

        return {
            "run_id": self.run_id,
            "target_color": self.target_color,
            "config": str(getattr(self.args, "v21_config", "")),
            "max_vel": str(getattr(self.args, "v21_max_vel", "")),
            "stage_name": run["stage_name"],
            "stage_index": str(run["index"]),
            "start_time": epoch_iso(run["start"]),
            "end_time": epoch_iso(run["end"]),
            "duration": number(run["duration"]),
            "goal_xyz": xyz(run["goal_xyz"]),
            "start_xyz": xyz(run["start_xyz"]),
            "end_xyz": xyz(run["end_xyz"]),
            "odom_source": self.primary_odom_topic,
            "path_length": number(run["path_length"]),
            "odom_mean_speed": number(run["odom_mean_speed"]),
            "odom_peak_speed": number(run["odom_peak_speed"]),
            "planner_cmd_mean_speed": number(run["planner_cmd_mean_speed"]),
            "planner_cmd_peak_speed": number(run["planner_cmd_peak_speed"]),
            "setpoint_mean_speed": number(run["setpoint_mean_speed"]),
            "setpoint_peak_speed": number(run["setpoint_peak_speed"]),
            "final_position_error": number(run["final_position_error"]),
            "safety_boundary_triggered": "true" if self.safety_boundary_triggered else "false",
            "recovery_triggered": "true" if self.recovery_triggered else "false",
            "recovery_completed": "true" if self.recovery_completed else "false",
            "recovery_duration": (
                "%.6f" % (self.recovery_end - self.recovery_start)
                if self.recovery_start is not None and self.recovery_end is not None else ""
            ),
            "replan_count": str(run["replan_count"]),
            "collision": self.collision or "false",
            "mission_success": mission.get("mission_success", ""),
            "bt_success": mission.get("bt_success", ""),
            "total_mission_time": mission.get("total_time", ""),
            "notes": "; ".join(self.notes),
        }

    def _append_v21_summary(self):
        if (
            not self.v21_enabled
            or self.v21_summary_written
            or self.v21_summary_path is None
            or not self.planning_runs
        ):
            return
        self.v21_summary_path.parent.mkdir(parents=True, exist_ok=True)
        mission = self.result_row()
        rows = [self._v21_row(run, mission) for run in self.planning_runs]
        exists = self.v21_summary_path.exists() and self.v21_summary_path.stat().st_size > 0
        if exists:
            with self.v21_summary_path.open("r", newline="", encoding="utf-8") as fp:
                old_header = next(csv.reader(fp), [])
            if old_header != V21_PLANNING_FIELDS:
                raise RuntimeError("V2.1 summary CSV schema mismatch: %s" % self.v21_summary_path)
        with self.v21_summary_path.open("a", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=V21_PLANNING_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerows(rows)
        self._write_v21_event("v21_summary", {"planning_runs": rows})
        self.v21_summary_written = True

    def finish(self, reason, when=None):
        if self.finished.is_set():
            return
        timestamp = when if when is not None else time.time()
        finalize_open = False
        with self.lock:
            if self.finished.is_set():
                return
            self.finish_reason = reason
            if self.command_seen and self.end_wall is None:
                self.end_wall = timestamp
                self.end_iso = epoch_iso(timestamp) if when is not None else now_iso()
            if reason == "mission_result":
                self.end_status = "completed"
            elif reason in ("keyboard_interrupt", "interrupted"):
                self.end_status = "interrupted"
            elif self.stuck_detected:
                self.end_status = "stuck"
            elif reason in ("timeout", "pre_mission_timeout", "mission_timeout", "replay_eof", "shutdown"):
                self.end_status = "timeout"
            else:
                self.end_status = reason
            self.finished.set()
            finalize_open = self.v21_enabled and bool(self.planning_open)
        if finalize_open:
            self._finalize_open_planning(timestamp)
        self._write_event("run_end", {
            "reason": reason,
            "mission_result": self.terminal_result,
            "mission_start_time": self.start_iso,
            "mission_end_time": self.end_iso,
        })
        if self.v21_enabled:
            self._append_v21_summary()

    def close(self):
        if not self.finished.is_set():
            self.finish("shutdown")
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass
        with self.lock:
            if self.log_fp is not None:
                self.log_fp.close()
                self.log_fp = None
            if self.v21_log_fp is not None:
                self.v21_log_fp.close()
                self.v21_log_fp = None

    def _failure_stage(self):
        for key in STAGE_FIELDS:
            if self.stages[key] != "success":
                return key.replace("_status", "")
        if self.stuck_detected:
            return "land"
        return "mission_result"

    def result_row(self):
        if self.start_wall is not None and self.end_wall is not None:
            total = max(0.0, self.end_wall - self.start_wall)
            total_text = "%.3f" % total
        else:
            total_text = ""
        aruco_time = ""
        if self.aruco_start and self.aruco_end:
            aruco_time = "%.3f" % max(0.0, self.aruco_end - self.aruco_start)
        balloon_time = ""
        if self.balloon_start and self.balloon_end:
            balloon_time = "%.3f" % max(0.0, self.balloon_end - self.balloon_start)
        result = self.terminal_result
        bt_success = self.bt_success or ("true" if result == "SUCCESS" else "false" if result else "")
        all_stages_success = all(self.stages[key] == "success" for key in STAGE_FIELDS)
        mission_success = "true" if bt_success == "true" and all_stages_success else "false" if self.command_seen else ""
        failure_stage = "" if mission_success == "true" else self._failure_stage() if self.command_seen else ""
        failure_reason = self.failure_reason
        if not failure_reason and self.finish_reason == "pre_mission_timeout":
            failure_reason = "pre_mission_timeout: no /mission_command received"
        if not failure_reason and self.finish_reason == "mission_timeout":
            failure_reason = "mission_timeout: no /mission_result received"
        if not failure_reason and self.end_status in ("timeout", "stuck", "interrupted"):
            failure_reason = self.stuck_reason if self.stuck_detected else "no /mission_result received"
        if result and result != "SUCCESS" and not failure_reason:
            failure_reason = "mission_result=" + result
        if result == "SUCCESS":
            unknown = [k.replace("_status", "") for k in STAGE_FIELDS if not self.stages[k]]
            if unknown:
                self.add_note("SUCCESS received while stages were unobserved: " + ",".join(unknown))
        notes = list(self.notes)
        if self.bt_xml_seen:
            notes.append("bt_planning_controls=" + json.dumps(self.bt_plan_controls, ensure_ascii=False, separators=(",", ":")))
        notes += [
            "rosout_events_logged",
            "setpoint_samples=%d" % self.setpoint_count,
            "target_detection_messages=%d" % self.target_detections,
        ]
        boundary_recovered = "" if not self.safety_boundary_triggered else "true" if self.boundary_recovered else "false"
        return {
            "run_id": self.run_id,
            "target_color": self.target_color,
            "start_time": self.start_iso,
            "end_time": self.end_iso,
            "total_time": total_text,
            "elapsed_time": total_text,
            "bt_success": bt_success,
            "mission_success": mission_success,
            "end_status": self.end_status,
            **self.stages,
            "aruco_detect_time": aruco_time,
            "balloon_search_time": balloon_time,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
            "safety_boundary_triggered": "true" if self.safety_boundary_triggered else "false" if self.command_seen else "",
            "boundary_first_time": self.boundary_first_time,
            "boundary_first_position": self.boundary_first_position,
            "boundary_violation_count": str(self.boundary_violation_count) if self.command_seen else "",
            "boundary_recovered": boundary_recovered,
            "notes": "; ".join(notes),
        }


def build_parser():
    p = argparse.ArgumentParser(description="Observe one official TCEI mission and append one CSV result.")
    p.add_argument("--color", choices=COLORS, default=None)
    p.add_argument("--output", default="/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv")
    p.add_argument("--logs-dir", default="/home/ubuntu/tcei_baseline_tools/results/logs")
    p.add_argument("--pre-mission-timeout", type=float, default=900.0,
                   help="Maximum seconds to wait for the first /mission_command.")
    p.add_argument("--mission-timeout", type=float, default=300.0,
                   help="Maximum seconds from the first /mission_command to /mission_result.")
    p.add_argument("--timeout", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--llm-script", default="/home/ubuntu/model/mission_once.py")
    p.add_argument("--no-launch-llm", action="store_true",
                   help="Do not start a process; observe immediately and start timing on the first /mission_command.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the exact official natural-language input and exit without ROS or files.")
    p.add_argument("--replay-jsonl", nargs="+", default=[],
                   help="Replay existing JSONL logs offline; ROS and simulation are not started.")
    p.add_argument("--replay-output", default="",
                   help="CSV path for offline replay rows. Defaults to stdout only.")
    p.add_argument("--v21-telemetry", action="store_true",
                   help="Subscribe to odom/planner/setpoint topics and write independent V2.1 telemetry.")
    p.add_argument("--v21-log-dir", default="",
                   help="Directory for independent V2.1 telemetry JSONL and planning summary CSV.")
    p.add_argument("--v21-summary", default="",
                   help="Independent V2.1 planning summary CSV path.")
    p.add_argument("--v21-config", default="",
                   help="Experiment config label, for example A0.")
    p.add_argument("--v21-max-vel", default="",
                   help="Experiment max_vel label/value, for example 0.30.")
    return p


def append_csv(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        # Migrate an older baseline CSV before appending the expanded schema.
        with path.open("r", newline="", encoding="utf-8") as old_fp:
            reader = csv.DictReader(old_fp)
            if reader.fieldnames != CSV_FIELDS:
                old_rows = list(reader)
                with path.open("w", newline="", encoding="utf-8") as new_fp:
                    writer = csv.DictWriter(new_fp, fieldnames=CSV_FIELDS)
                    writer.writeheader()
                    for old_row in old_rows:
                        writer.writerow({key: old_row.get(key, "") for key in CSV_FIELDS})
    with path.open("a", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})


def infer_replay_color(path):
    stem = Path(path).stem.lower()
    for color in COLORS:
        if re.search(r"(?:^|[_-])%s(?:$|[_-])" % color, stem):
            return color
    return "red"


def replay_jsonl(path):
    """Replay recorded evidence without importing ROS or starting a process."""
    path = Path(path)
    color = infer_replay_color(path)
    args = argparse.Namespace(color=color)
    observer = RunObserver(args, log_path=None, run_id=path.stem, record=False)
    last_time = None
    with path.open("r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                observer.add_note("replay skipped invalid JSON line %d: %s" % (line_no, exc))
                continue
            event_time = parse_event_time(record.get("wall_time"))
            if event_time is not None:
                last_time = event_time
            observer.replay_record(record)
    if observer.command_seen and not observer.finished.is_set():
        observer.finish("replay_eof", when=last_time)
    return observer.result_row()


def write_rows_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})


def main():
    args = build_parser().parse_args()
    # Keep older invocations usable while making the two lifecycle windows explicit.
    if args.timeout is not None:
        args.mission_timeout = args.timeout
    if args.replay_jsonl:
        rows = [replay_jsonl(path) for path in args.replay_jsonl]
        if args.replay_output:
            write_rows_csv(args.replay_output, rows)
            print("csv=%s" % args.replay_output)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not args.color:
        print("--color is required unless --replay-jsonl is used", file=sys.stderr)
        return 2
    task = make_task(args.color)
    if args.dry_run:
        print(task)
        return 0
    if rospy is None:
        print("ROS Python imports unavailable: %s" % ROS_IMPORT_ERROR, file=sys.stderr)
        return 2

    results_dir = Path(args.logs_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    provisional_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
    log_path = results_dir / (provisional_id + "_" + args.color + ".jsonl")
    v21_log_path = None
    v21_summary_path = None
    if args.v21_telemetry:
        v21_dir = Path(args.v21_log_dir) if args.v21_log_dir else (
            results_dir.parent / "v2_1_ego_velocity" / "experiments"
        )
        v21_dir.mkdir(parents=True, exist_ok=True)
        v21_log_path = v21_dir / (provisional_id + "_" + args.color + "_telemetry.jsonl")
        v21_summary_path = Path(args.v21_summary) if args.v21_summary else (v21_dir / "planning_runs.csv")
    observer = RunObserver(
        args,
        log_path,
        v21_log_path=v21_log_path,
        v21_summary_path=v21_summary_path,
    )
    rospy.init_node("tcei_baseline_observer", anonymous=True, disable_signals=True)

    rospy.Subscriber("/mission_command", String, observer.on_mission_command, queue_size=10)
    rospy.Subscriber("/mission_result", String, observer.on_mission_result, queue_size=10)
    rospy.Subscriber("/rosout", Log, observer.on_rosout, queue_size=200)
    rospy.Subscriber("/aruco/detected_id", Int32, observer.on_aruco_id, queue_size=10)
    try:
        from common_msgs.msg import Objects
        rospy.Subscriber("/objects", Objects, observer.on_objects, queue_size=10)
    except Exception as exc:
        observer.add_note("common_msgs/Objects unavailable: " + str(exc))
    try:
        from mavros_msgs.msg import PositionTarget, State
        rospy.Subscriber("/mavros/setpoint_raw/local", PositionTarget, observer.on_setpoint, queue_size=50)
        rospy.Subscriber("/mavros/state", State, observer.on_state, queue_size=10)
    except Exception as exc:
        observer.add_note("mavros messages unavailable: " + str(exc))
    try:
        from quadrotor_msgs.msg import PositionCommand
        rospy.Subscriber("/planning/pos_cmd", PositionCommand,
                         lambda msg: observer.on_generic("/planning/pos_cmd", msg), queue_size=10)
    except Exception as exc:
        observer.add_note("quadrotor_msgs unavailable: " + str(exc))
    if args.v21_telemetry:
        try:
            from nav_msgs.msg import Odometry
            rospy.Subscriber(
                "/mavros/local_position/odom", Odometry,
                lambda msg: observer.on_odom("/mavros/local_position/odom", msg),
                queue_size=100,
            )
            rospy.Subscriber(
                "/rflysim/uav1/local/odom", Odometry,
                lambda msg: observer.on_odom("/rflysim/uav1/local/odom", msg),
                queue_size=100,
            )
        except Exception as exc:
            observer.add_note("nav_msgs/Odometry unavailable: " + str(exc))

    print("run_id=%s" % observer.run_id)
    print("natural_language_task=%s" % task)
    if args.v21_telemetry:
        print("v21_telemetry_log=%s" % v21_log_path)
        print("v21_planning_summary=%s" % v21_summary_path)
    if args.no_launch_llm:
        print("Observer ready: waiting for first /mission_command; timing starts automatically.")
        observer._write_event("observer_ready", {
            "mode": "no_launch_llm",
            "waiting_for": "/mission_command",
        })
    else:
        if not Path(args.llm_script).exists():
            observer.add_note("llm script not found: " + args.llm_script)
            print("official LLM script not found: %s" % args.llm_script, file=sys.stderr)
        else:
            cmd = [sys.executable, args.llm_script, task]
            observer._write_event("launch_official_llm", {"argv": cmd})
            observer.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, bufsize=1
            )
            def read_llm_output():
                for line in observer.process.stdout:
                    observer._write_event("mission_once_stdout", {"line": line.rstrip("\n")})
            threading.Thread(target=read_llm_output, daemon=True).start()

    pre_mission_deadline = observer.monitor_start_wall + args.pre_mission_timeout
    mission_deadline = None
    try:
        while not rospy.is_shutdown() and not observer.finished.is_set():
            now = time.time()
            if not observer.command_seen:
                if now >= pre_mission_deadline:
                    observer.add_note(
                        "pre-mission timeout after %.1f seconds; no /mission_command received"
                        % args.pre_mission_timeout
                    )
                    observer.finish("pre_mission_timeout")
                    break
            else:
                if mission_deadline is None:
                    mission_deadline = observer.start_wall + args.mission_timeout
                if now >= mission_deadline:
                    observer.add_note(
                        "mission timeout after %.1f seconds; no terminal /mission_result received"
                        % args.mission_timeout
                    )
                    observer.finish("mission_timeout")
                    break
            time.sleep(0.2)
    except KeyboardInterrupt:
        observer.add_note("interrupted by user")
        observer.finish("keyboard_interrupt")
    finally:
        if not observer.command_seen:
            observer.close()
            print(
                "PRE_MISSION_TIMEOUT: no /mission_command received within %.1f seconds; "
                "no CSV result was generated." % args.pre_mission_timeout,
                file=sys.stderr,
            )
        else:
            row = observer.result_row()
            append_csv(args.output, row)
            observer.close()
            print(json.dumps(row, ensure_ascii=False, indent=2))
            print("csv=%s" % args.output)
            if observer.end_status == "timeout":
                print(
                    "MISSION_TIMEOUT: no terminal /mission_result received within %.1f seconds."
                    % args.mission_timeout,
                    file=sys.stderr,
                )
        print("raw_log=%s" % log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

