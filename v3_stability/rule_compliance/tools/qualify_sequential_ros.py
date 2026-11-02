#!/usr/bin/env python3
"""Exercise the compiled executor using only an isolated ROS master and fake FCU."""
import argparse
import hashlib
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import rospy
from mavros_msgs.msg import PositionTarget, State
from mavros_msgs.srv import CommandBool, CommandBoolResponse, SetMode, SetModeResponse
from nav_msgs.msg import Odometry
from std_msgs.msg import String


NS = "/qualification"
TERMINAL = {"SUCCESS", "FAILURE", "REJECTED", "ABORTED", "TIMEOUT"}


class Probe:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.output).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.log = (self.out / "events.jsonl").open("w", encoding="utf-8")
        self.lock = threading.Lock()
        self.statuses, self.readies, self.targets, self.modes, self.arms = [], [], [], [], []
        self.armed, self.mode, self.odom_enabled = False, "MANUAL", True
        self.state_enabled, self.bad_odom = True, False
        self.position = (2.0, 1.0, 1.0)
        self.yaw = 0.0
        self.process = None
        self.mode_sent = True
        self.state_period, self.state_stamp_age, self.last_state_publish = 0.0, 0.0, 0.0
        self.counter = 0
        self.results = []
        self.state_pub = rospy.Publisher(NS + "/fcu/state", State, queue_size=10)
        self.odom_pub = rospy.Publisher(NS + "/fcu/odom", Odometry, queue_size=10)
        self.request_pub = rospy.Publisher(NS + "/mission_request", String, queue_size=10)
        self.abort_pub = rospy.Publisher(NS + "/mission_abort", String, queue_size=10)
        self.subs = [
            rospy.Subscriber(NS + "/mission_status", String, self.on_status),
            rospy.Subscriber(NS + "/mission_ready", String, self.on_ready),
            rospy.Subscriber(NS + "/fcu/setpoint", PositionTarget, self.on_target),
        ]
        self.services = [
            rospy.Service(NS + "/fcu/set_mode", SetMode, self.on_mode),
            rospy.Service(NS + "/fcu/arming", CommandBool, self.on_arm),
        ]
        self.timer = rospy.Timer(rospy.Duration(0.05), self.telemetry)

    def event(self, kind, value):
        with self.lock:
            self.log.write(json.dumps({"monotonic": time.monotonic(), "kind": kind, "value": value}) + "\n")
            self.log.flush()

    def on_status(self, msg):
        data = json.loads(msg.data)
        self.statuses.append(data)
        self.event("status", data)

    def on_ready(self, msg):
        data = json.loads(msg.data)
        self.readies.append(data)
        self.event("ready", data)

    def on_target(self, msg):
        data = {"mask": msg.type_mask, "frame": msg.coordinate_frame, "source": msg.header.frame_id,
                "position": [msg.position.x, msg.position.y, msg.position.z],
                "velocity": [msg.velocity.x, msg.velocity.y, msg.velocity.z],
                "yaw": msg.yaw, "yaw_rate": msg.yaw_rate}
        self.targets.append((time.monotonic(), data))
        self.event("setpoint", data)

    def on_mode(self, req):
        self.modes.append((time.monotonic(), req.custom_mode))
        self.event("mock_set_mode", {"custom_mode": req.custom_mode, "mode_sent": self.mode_sent})
        return SetModeResponse(mode_sent=self.mode_sent)

    def on_arm(self, req):
        self.arms.append((time.monotonic(), req.value))
        self.event("mock_arming", {"value": req.value, "success": False})
        return CommandBoolResponse(success=False, result=1)

    def telemetry(self, _):
        now = rospy.Time.now()
        if self.state_enabled and time.monotonic() - self.last_state_publish >= self.state_period:
            self.last_state_publish = time.monotonic()
            state = State()
            state.header.stamp = now - rospy.Duration(self.state_stamp_age)
            state.connected, state.armed, state.mode = True, self.armed, self.mode
            self.state_pub.publish(state)
        if self.odom_enabled:
            odom = Odometry()
            odom.header.stamp = now
            odom.pose.pose.position.x, odom.pose.pose.position.y, odom.pose.pose.position.z = self.position
            odom.pose.pose.orientation.z = math.sin(self.yaw / 2.0)
            odom.pose.pose.orientation.w = 0.0 if self.bad_odom else math.cos(self.yaw / 2.0)
            self.odom_pub.publish(odom)

    def wait(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not rospy.is_shutdown():
            if self.process is not None and self.process.poll() is not None:
                raise AssertionError("executor exited: %s" % self.process.returncode)
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        raise AssertionError("condition timed out after %.1fs" % timeout)

    def settle(self, seconds=0.25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(0.02)

    def start(self, name, command_timeout=4.0, safety_enabled=False):
        self.stop()
        self.state_period, self.state_stamp_age, self.last_state_publish = 0.0, 0.0, 0.0
        self.armed, self.mode = False, "MANUAL"
        self.yaw = 0.0
        self.mode_sent = True
        self.state_enabled, self.odom_enabled, self.bad_odom = True, True, False
        self.statuses.clear()
        self.readies.clear()
        self.targets.clear()
        self.modes.clear()
        self.arms.clear()
        params = {"fcu_state_topic": NS + "/fcu/state", "odom_topic": NS + "/fcu/odom",
                  "pos_tgt_topic": NS + "/fcu/setpoint", "set_mode_service": NS + "/fcu/set_mode",
                  "arm_service": NS + "/fcu/arming", "safety/enabled": safety_enabled,
                  "safety/x_min": -1.0, "safety/x_max": 6.0,
                  "safety/y_min": -3.0, "safety/y_max": 3.0,
                  "safety/z_min": -0.1, "safety/z_max": 2.5,
                  "safety/recovery_target_margin": 0.30,
                  "safety/release_margin": 0.15, "safety/recovery_confirm_time": 0.50,
                  "land/return_pos": "0.7;-0.3;0.6", "land/return_yaw": 0.4,
                  "cam2body_R": [0, 0, 1, -1, 0, 0, 0, -1, 0],
                  "cam2body_T": [0.1, 0.04, 0.05]}
        for color, zone in (("red", "A"), ("purple", "B"), ("blue", "C")):
            params["balloon_color_" + color] = zone
            params["balloon_zone_" + zone + "/approach_pos"] = "2.0;1.0;1.0"
            params["balloon_zone_" + zone + "/goal"] = "2.0;1.0;1.0"
            params["balloon_zone_" + zone + "/yaw"] = 0.0
        for key, value in params.items():
            rospy.set_param(NS + "/" + key, value)
        env = dict(os.environ, ROS_NAMESPACE=NS)
        command = [str(Path(self.args.executor).resolve()), "__name:=executor", "__ns:=" + NS,
                   "_mode:=llm", "_command_timeout_s:=" + str(command_timeout)]
        command += ["/" + topic + ":=" + NS + "/" + topic for topic in
                    ("mission_request", "mission_abort", "mission_ready", "mission_status")]
        # These remaps also isolate legacy plugin defaults with absolute topic names.
        command += ["/rflysim/uav1/local/odom:=" + NS + "/fcu/odom",
                    "/mavros/setpoint_raw/local:=" + NS + "/fcu/setpoint",
                    "/mavros/state:=" + NS + "/fcu/state",
                    "/mavros/set_mode:=" + NS + "/fcu/set_mode",
                    "/mavros/cmd/arming:=" + NS + "/fcu/arming",
                    "/objects:=" + NS + "/objects", "/planning/pos_cmd:=" + NS + "/planning/pos_cmd",
                    "/move_base_simple/goal:=" + NS + "/goal", "/aruco/enable:=" + NS + "/aruco/enable",
                    "/aruco/detected_id:=" + NS + "/aruco/id"]
        self.executor_log = (self.out / (name + ".executor.log")).open("w", encoding="utf-8")
        self.event("launch", {"command": command, "params": params})
        self.process = subprocess.Popen(command, env=env, stdout=self.executor_log, stderr=subprocess.STDOUT)
        ready = self.wait(lambda: self.readies and self.readies[-1])
        self.epoch = ready["server_epoch"]
        self.session = name
        self.wait(lambda: self.request_pub.get_num_connections() and self.abort_pub.get_num_connections())
        self.settle()
        self.graph_gate()
        if self.args.runtime_library:
            output = self.out / (name + ".runtime-identity.json")
            audit_command = [sys.executable, str(Path(__file__).with_name("audit_loaded_process.py")),
                             "--pid", str(self.process.pid), "--executable", self.args.executor,
                             "--output", str(output)]
            for library in self.args.runtime_library:
                audit_command += ["--library", library]
            subprocess.run(audit_command, check=True, timeout=30)
            maps = Path("/proc/%d/maps" % self.process.pid).read_text()
            assert not any(word in maps.lower() for word in ("fm9g_balloon_stage", "multimodal")), maps
            self.event("runtime_identity", json.loads(output.read_text()))
        reset = self.request(reset=True)
        self.expect(reset, "SUCCESS", "RESET")
        self.wait(lambda: self.readies[-1].get("session_id") == self.session)

    def graph_gate(self):
        code, text, state = rospy.get_master().getSystemState()
        assert code == 1, text
        for entries in state:
            for resource, nodes in entries:
                for node in nodes:
                    if node == NS + "/executor":
                        assert resource == NS or resource.startswith(NS + "/") or resource in ("/rosout", "/rosout_agg"), (resource, nodes)
        self.event("graph_gate", "executor resources isolated")

    def request(self, command=None, reset=False, request_id=None):
        self.counter += 1
        payload = {"protocol": 1, "server_epoch": self.epoch, "session_id": self.session,
                   "request_id": request_id or "request-%d" % self.counter}
        payload.update({"reset": True} if reset else {"command": command})
        self.send(payload)
        return payload

    def send(self, payload, abort=False):
        self.event("abort" if abort else "request", payload)
        (self.abort_pub if abort else self.request_pub).publish(String(data=json.dumps(payload)))

    def expect(self, payload, status, reason=None, after=0):
        def match():
            return next((s for s in self.statuses[after:] if s.get("request_id") == payload["request_id"]
                         and s.get("status") == status and (reason is None or s.get("reason") == reason)), None)
        value = self.wait(match)
        assert value["server_epoch"] == self.epoch and value["session_id"] == self.session, value
        return value

    def expect_telemetry_failure(self, payload, fallback, unhealthy):
        terminal = self.expect(payload, "FAILURE")
        parts = terminal["reason"].split("; ")
        assert len(parts) == 3 and parts[0] == "TELEMETRY_LOST_DURING_COMMAND" and parts[2] == fallback, terminal
        fields = dict(item.split("=", 1) for item in parts[1].split())
        required = {"state_fresh", "state_received", "state_receive_age_s", "state_stamp_valid",
                    "state_source_age_s", "state_limit_s", "connected", "armed", "mode",
                    "odom_fresh", "odom_received", "odom_receive_age_s", "odom_stamp_valid",
                    "odom_source_age_s", "odom_limit_s", "position_finite", "quaternion_finite",
                    "quaternion_norm_squared"}
        assert set(fields) == required, terminal
        assert fields["state_received"] == "1" and fields["connected"] == "1", terminal
        assert fields["odom_received"] == "1" and fields["mode"] == "MANUAL", terminal
        assert fields["armed"] == "0" and fields["state_stamp_valid"] == "1", terminal
        assert fields["odom_stamp_valid"] == "1" and fields["position_finite"] == "1", terminal
        assert float(fields["state_limit_s"]) == 2.5 and float(fields["odom_limit_s"]) == 1.0, terminal
        if unhealthy == "invalid_odom":
            assert fields["state_fresh"] == "1" and fields["odom_fresh"] == "0", terminal
            assert fields["quaternion_finite"] == "1" and float(fields["quaternion_norm_squared"]) == 0.0, terminal
        elif unhealthy == "stale_odom":
            assert fields["state_fresh"] == "1" and fields["odom_fresh"] == "0", terminal
            assert float(fields["odom_receive_age_s"]) > 1.0, terminal
        elif unhealthy == "stale_state":
            assert fields["state_fresh"] == "0" and fields["odom_fresh"] == "1", terminal
            assert float(fields["state_receive_age_s"]) > 2.5, terminal
        elif unhealthy == "state_source_stale":
            assert fields["state_fresh"] == "0" and fields["odom_fresh"] == "1", terminal
            assert fields["state_stamp_valid"] == "1" and float(fields["state_source_age_s"]) > 2.5, terminal
        return terminal

    def stop(self):
        if self.process is not None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.executor_log.close()
            self.process = None

    def protocol(self):
        self.start("protocol")
        self.send({"protocol": 1})
        self.wait(lambda: any(s.get("reason") == "INVALID_REQUEST" for s in self.statuses))
        unknown = self.request("cross_frame")
        self.expect(unknown, "REJECTED", "NOT_AIRBORNE")
        pending = self.request("takeoff")
        self.expect(pending, "ACCEPTED")
        busy = self.request("land")
        self.expect(busy, "REJECTED", "BUSY")
        index = len(self.statuses)
        self.send(pending)
        self.expect(pending, "ACCEPTED", after=index)
        abort = {k: v for k, v in pending.items() if k != "command"}
        self.send(abort, abort=True)
        self.expect(pending, "ABORTED")
        self.wait(lambda: self.readies[-1].get("state") == "RECOVERY_REQUIRED")
        self.wait(lambda: any(t[1]["mask"] == 3064 and t[1]["position"] == [-1.0, 2.0, 1.0] for t in self.targets))
        index = len(self.statuses)
        self.send(pending)
        self.expect(pending, "ABORTED", after=index)
        self.request(reset=True)
        # A previously used session cannot be reset again, even while disarmed.
        self.wait(lambda: any(s.get("reason") == "SESSION_ID_REUSED" for s in self.statuses))
        self.session = "protocol-second"
        reset = self.request(reset=True)
        self.expect(reset, "SUCCESS", "RESET")
        tombstone = {"protocol": 1, "server_epoch": self.epoch, "session_id": self.session,
                     "request_id": "cancel-before-request"}
        self.send(tombstone, abort=True)
        self.settle()
        cancelled = self.request("takeoff", request_id=tombstone["request_id"])
        self.expect(cancelled, "REJECTED", "CANCELLED")
        self.settle(0.3)
        assert not any(s.get("request_id") == cancelled["request_id"] and s.get("status") == "ACCEPTED" for s in self.statuses)
        assert not any(mode == "AUTO.LAND" for _, mode in self.modes)

    def stale(self, invalid=False):
        self.start("invalid-odom" if invalid else "stale-odom")
        request = self.request("takeoff")
        self.expect(request, "ACCEPTED")
        self.wait(lambda: bool(self.targets))
        if invalid:
            self.bad_odom = True
        else:
            self.odom_enabled = False
        self.expect_telemetry_failure(request, "AUTO_LAND_REQUESTED",
                                      "invalid_odom" if invalid else "stale_odom")
        self.wait(lambda: any(mode == "AUTO.LAND" for _, mode in self.modes))
        fallback_time = next(t for t, mode in self.modes if mode == "AUTO.LAND")
        self.wait(lambda: sum(t > fallback_time and d["mask"] == 1991 and d["velocity"] == [0.0, 0.0, 0.0]
                              and d["yaw_rate"] == 0.0 for t, d in self.targets) >= 5)
        self.wait(lambda: self.readies[-1].get("state") == "RECOVERY_REQUIRED")
        assert not self.armed

    def takeoff_success(self):
        self.start("takeoff-success")
        request = self.request("takeoff")
        self.expect(request, "ACCEPTED")
        self.wait(lambda: bool(self.targets))
        self.mode, self.armed, self.position = "OFFBOARD", True, (0.0, 0.0, 1.0)
        self.expect(request, "SUCCESS")
        self.wait(lambda: self.readies[-1].get("last_request_id") == request["request_id"]
                  and self.readies[-1].get("state") == "IDLE")
        before = len(self.statuses)
        self.send(request)
        self.expect(request, "SUCCESS", after=before)
        self.wait(lambda: sum(d["mask"] == 3064 and d["position"] == [0.0, 0.0, 1.0]
                              for _, d in self.targets) >= 5)

    def timeout(self):
        self.start("timeout")
        request = self.request("takeoff")
        self.expect(request, "ACCEPTED")
        self.expect(request, "TIMEOUT")
        self.wait(lambda: self.readies[-1].get("state") == "RECOVERY_REQUIRED")
        assert not any(mode == "AUTO.LAND" for _, mode in self.modes)

    def landing(self, emergency):
        self.start("emergency-land" if emergency else "normal-land", command_timeout=12.0)
        # This flag is synthetic telemetry only. The mock never arms an FCU.
        self.mode, self.armed = "OFFBOARD", True
        self.settle()
        request = self.request("emergency_land" if emergency else "land")
        self.expect(request, "ACCEPTED")
        if emergency:
            self.wait(lambda: any(mode == "AUTO.LAND" for _, mode in self.modes))
            assert not self.targets, "direct Land must not introduce a GoTo setpoint"
            assert not any(s.get("request_id") == request["request_id"] and s.get("status") == "SUCCESS" for s in self.statuses)
            self.armed = False
            self.mode = "AUTO.LAND"
            self.expect(request, "SUCCESS")
        else:
            self.wait(lambda: any(d["mask"] == 3064 and d["position"] == [0.3, 0.7, 0.6]
                                  and abs(d["yaw"] - (0.4 + math.pi / 2.0)) < 1e-3
                                  for _, d in self.targets))
            assert not any(mode == "AUTO.LAND" for _, mode in self.modes), "normal land must return home before Land"
            self.position = (0.7, -0.3, 0.6)
            self.yaw = 0.4
            self.wait(lambda: any(mode == "AUTO.LAND" for _, mode in self.modes))
            self.mode, self.armed = "AUTO.LAND", False
            self.expect(request, "SUCCESS")
        assert not self.arms, "landing must never request arming"

    def fallback(self, denied=False, state_loss=False):
        self.start("fallback-state-loss" if state_loss else
                   "fallback-denied" if denied else "fallback-unenacted")
        self.mode_sent = not denied
        request = self.request("takeoff")
        self.expect(request, "ACCEPTED")
        self.wait(lambda: bool(self.targets))
        if state_loss:
            self.state_enabled = False
        else:
            self.odom_enabled = False
        self.expect_telemetry_failure(request, "AUTO_LAND_REQUEST_FAILED" if denied else
                                      "AUTO_LAND_REQUESTED", "stale_state" if state_loss else "stale_odom")
        self.wait(lambda: self.readies[-1].get("state") == "RECOVERY_REQUIRED")
        start = time.monotonic()
        self.settle(0.5)
        targets = [d for t, d in self.targets if t > start]
        assert len(targets) >= 5 and all(d["mask"] == 1991 and d["velocity"] == [0.0, 0.0, 0.0]
                                         and d["yaw_rate"] == 0.0 for d in targets), targets
        assert self.mode == "MANUAL", "mock service must not imply observed mode transition"
        assert not any(s.get("request_id") == request["request_id"] and s.get("status") == "SUCCESS"
                       for s in self.statuses)

    def land_abort(self):
        self.start("land-abort")
        self.mode, self.armed = "OFFBOARD", True
        self.settle()
        request = self.request("land")
        self.expect(request, "ACCEPTED")
        self.wait(lambda: bool(self.targets))
        self.send({k: v for k, v in request.items() if k != "command"}, abort=True)
        self.expect(request, "ABORTED", "AUTO_LAND_REQUESTED")
        self.wait(lambda: any(mode == "AUTO.LAND" for _, mode in self.modes))
        self.wait(lambda: self.readies[-1].get("state") == "RECOVERY_REQUIRED")
        assert self.armed
        assert not any(s.get("request_id") == request["request_id"] and s.get("status") == "SUCCESS"
                       for s in self.statuses)
        assert not self.arms

    def emergency_stale_odom(self):
        self.start("emergency-stale-odom")
        self.mode, self.armed, self.odom_enabled = "OFFBOARD", True, False
        self.settle(1.2)
        request = self.request("emergency_land")
        self.expect(request, "ACCEPTED")
        self.wait(lambda: any(mode == "AUTO.LAND" for _, mode in self.modes))
        assert all(d["mask"] == 1991 and d["velocity"] == [0.0, 0.0, 0.0]
                   and d["yaw_rate"] == 0.0 for _, d in self.targets), self.targets
        self.mode, self.armed = "AUTO.LAND", False
        self.expect(request, "SUCCESS")
        assert not self.arms

    def state_1hz(self):
        self.start("state-1hz", command_timeout=15.0)
        self.state_period = 1.005
        request = self.request("takeoff")
        self.expect(request, "ACCEPTED")
        deadline = time.monotonic() + 10.5
        while time.monotonic() < deadline:
            assert self.process.poll() is None, "executor exited during 1Hz telemetry"
            assert not any(s.get("request_id") == request["request_id"] and s.get("status") in TERMINAL
                           for s in self.statuses), self.statuses
            self.settle(0.1)
        self.send({k: v for k, v in request.items() if k != "command"}, abort=True)
        self.expect(request, "ABORTED")
        assert not any(mode == "AUTO.LAND" for _, mode in self.modes)
        self.event("state_1hz_gate", {"state_period_s": 1.005, "healthy_observation_s": 10.5})

    def state_source_stale(self):
        self.start("state-source-stale")
        request = self.request("takeoff")
        self.expect(request, "ACCEPTED")
        self.wait(lambda: bool(self.targets))
        self.state_stamp_age = 3.0
        self.expect_telemetry_failure(request, "AUTO_LAND_REQUESTED", "state_source_stale")
        self.wait(lambda: self.readies[-1].get("state") == "RECOVERY_REQUIRED")
        self.wait(lambda: any(d["mask"] == 1991 and d["velocity"] == [0.0, 0.0, 0.0]
                              for _, d in self.targets))
        assert not self.armed

    def safety_release(self, active=False):
        self.start("safety-active-release" if active else "safety-idle-release",
                   command_timeout=12.0, safety_enabled=True)
        if active:
            self.mode, self.armed = "OFFBOARD", True
            self.settle()
        request = self.request("land" if active else "takeoff")
        self.expect(request, "ACCEPTED")
        if active:
            self.wait(lambda: any(d.get("source") == "GoTo" for _, d in self.targets))
        else:
            self.wait(lambda: bool(self.targets))
            self.mode, self.armed, self.position = "OFFBOARD", True, (0.0, 0.0, 1.0)
            self.expect(request, "SUCCESS")
            self.wait(lambda: self.readies[-1].get("state") == "IDLE")
        self.position = (6.2, 1.0, 1.0)
        self.wait(lambda: self.targets[-1][1].get("source") == "safety_recovery")
        self.position, self.yaw = (5.5, 0.8, 1.2), 0.3
        self.wait(lambda: self.targets[-1][1].get("source") != "safety_recovery")
        start = time.monotonic()
        self.settle(0.5)
        targets = [d for t, d in self.targets if t >= start]
        assert len(targets) >= 10, targets
        if active:
            assert all(d.get("source") == "GoTo" for d in targets), targets
            self.send({k: v for k, v in request.items() if k != "command"}, abort=True)
            self.expect(request, "ABORTED", "AUTO_LAND_REQUESTED")
        else:
            assert all(d.get("source") == "safety_recovery_release" and d["mask"] == 3064
                       and all(abs(a-b) < 1e-6 for a, b in zip(d["position"], [-0.8, 5.5, 1.2]))
                       and abs(d["yaw"] - (0.3 + math.pi/2)) < 1e-5 for d in targets), targets
            # A later explicit command must still supersede the release hold.
            followup = self.request("land")
            self.expect(followup, "ACCEPTED")
            self.wait(lambda: self.targets[-1][1].get("source") == "GoTo")
            self.send({k: v for k, v in followup.items() if k != "command"}, abort=True)
            self.expect(followup, "ABORTED", "AUTO_LAND_REQUESTED")
        self.event("safety_release_gate", {"active": active, "observed_release_targets": len(targets)})

    def run(self):
        cases = [("protocol", self.protocol), ("takeoff_success", self.takeoff_success), ("stale_odom", self.stale),
                 ("invalid_odom", lambda: self.stale(True)), ("timeout", self.timeout),
                 ("normal_land", lambda: self.landing(False)),
                 ("emergency_land", lambda: self.landing(True)),
                 ("mode_denied", lambda: self.fallback(denied=True)),
                 ("mode_unenacted", self.fallback),
                 ("stale_state", lambda: self.fallback(state_loss=True)),
                 ("land_abort", self.land_abort),
                 ("emergency_stale_odom", self.emergency_stale_odom),
                 ("state_1hz", self.state_1hz),
                 ("state_source_stale", self.state_source_stale),
                 ("safety_idle_release", self.safety_release),
                 ("safety_active_release", lambda: self.safety_release(True))]
        if self.args.cases:
            selected = set(self.args.cases.split(","))
            unknown = selected - {name for name, _ in cases}
            if unknown:
                raise ValueError("unknown cases: %r" % sorted(unknown))
            cases = [(name, case) for name, case in cases if name in selected]
        try:
            for name, case in cases:
                try:
                    case()
                    self.results.append({"case": name, "passed": True})
                except Exception as exc:
                    self.results.append({"case": name, "passed": False, "error": repr(exc)})
                finally:
                    self.stop()
                self.event("case_result", self.results[-1])
        finally:
            self.timer.shutdown()
            self.stop()
            summary = {"scope": "isolated mocked ROS; no PX4/MAVROS or flight", "results": self.results,
                       "executor_sha256": hashlib.sha256(Path(self.args.executor).read_bytes()).hexdigest()}
            (self.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            self.log.close()
        print(json.dumps(summary, indent=2))
        return 0 if all(row["passed"] for row in self.results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", required=True, help="exact compiled bt_ros executable")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cases", help="comma-separated case names; default runs all")
    parser.add_argument("--runtime-library", action="append", default=[],
                        help="require this exact library to be mapped in each executor process")
    args = parser.parse_args()
    uri = urlparse(os.environ.get("ROS_MASTER_URI", ""))
    if uri.hostname not in ("127.0.0.1", "localhost") or uri.port != 11321:
        parser.error("requires explicit isolated ROS_MASTER_URI=http://127.0.0.1:11321")
    rospy.init_node("qualification_probe", anonymous=True)
    code, text, state = rospy.get_master().getSystemState()
    if code != 1:
        raise RuntimeError(text)
    nodes = {node for group in state for _, members in group for node in members}
    allowed = {"/rosout", rospy.get_name()}
    if nodes - allowed:
        raise RuntimeError("isolated master is not empty: %r" % sorted(nodes - allowed))
    return Probe(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
