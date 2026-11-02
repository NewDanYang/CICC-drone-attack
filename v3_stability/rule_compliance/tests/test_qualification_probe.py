import importlib.util
import inspect
import math
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "qualify_sequential_ros.py"


def load_probe():
    modules = {}
    rospy = types.ModuleType("rospy")
    rospy.get_master = lambda: None
    rospy.get_name = lambda: "/qualification_probe"
    rospy.init_node = lambda *args, **kwargs: None
    rospy.is_shutdown = lambda: False
    modules["rospy"] = rospy
    for package in ("mavros_msgs", "nav_msgs", "std_msgs"):
        modules[package] = types.ModuleType(package)
    for name, symbols in {
        "mavros_msgs.msg": ("PositionTarget", "State"),
        "mavros_msgs.srv": ("CommandBool", "CommandBoolResponse", "SetMode", "SetModeResponse"),
        "nav_msgs.msg": ("Odometry",),
        "std_msgs.msg": ("String",),
    }.items():
        module = types.ModuleType(name)
        for symbol in symbols:
            setattr(module, symbol, type(symbol, (), {}))
        modules[name] = module
    spec = importlib.util.spec_from_file_location("qualification_probe_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, rospy


class Master:
    def __init__(self, state):
        self.state = state

    def getSystemState(self):
        return 1, "ok", self.state


class QualificationProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module, cls.rospy = load_probe()

    def probe(self, reason):
        probe = self.module.Probe.__new__(self.module.Probe)
        probe.epoch = "epoch"
        probe.session = "session"
        probe.statuses = [{"request_id": "request", "status": "FAILURE", "reason": reason,
                           "server_epoch": "epoch", "session_id": "session"}]
        probe.wait = lambda predicate, timeout=8.0: predicate() or self.fail("status did not match")
        return probe

    def diagnostics(self, **changes):
        fields = dict(state_fresh="1", state_received="1", state_receive_age_s="0.1",
                      state_stamp_valid="1", state_source_age_s="0.1", state_limit_s="2.5",
                      connected="1", armed="0", mode="MANUAL", odom_fresh="0",
                      odom_received="1", odom_receive_age_s="1.2", odom_stamp_valid="1",
                      odom_source_age_s="0.1", odom_limit_s="1", position_finite="1",
                      quaternion_finite="1", quaternion_norm_squared="1")
        fields.update(changes)
        return " ".join("%s=%s" % item for item in fields.items())

    def reason(self, diagnostics, fallback="AUTO_LAND_REQUESTED"):
        return "TELEMETRY_LOST_DURING_COMMAND; %s; %s" % (diagnostics, fallback)

    def test_diagnostic_suffix_accepts_expected_failure_and_rejects_missing_evidence(self):
        payload = {"request_id": "request"}
        healthy = self.reason(self.diagnostics())
        self.probe(healthy).expect_telemetry_failure(payload, "AUTO_LAND_REQUESTED", "stale_odom")
        for reason in ("TELEMETRY_LOST_DURING_COMMAND; AUTO_LAND_REQUESTED",
                       self.reason(self.diagnostics(odom_fresh="1")),
                       self.reason(self.diagnostics().replace("odom_received=1 ", "")),
                       self.reason(self.diagnostics(), "AUTO_LAND_REQUEST_FAILED"),
                       self.reason(self.diagnostics().replace("odom_receive_age_s=1.2", "odom_receive_age_s=0.2"))):
            with self.subTest(reason=reason), self.assertRaises(AssertionError):
                self.probe(reason).expect_telemetry_failure(payload, "AUTO_LAND_REQUESTED", "stale_odom")

    def test_state_source_age_and_fallback_denial_require_specific_diagnostics(self):
        payload = {"request_id": "request"}
        diagnostic = self.diagnostics(state_fresh="0", state_source_age_s="3.0",
                                      odom_fresh="1", odom_receive_age_s="0.1")
        self.probe(self.reason(diagnostic)).expect_telemetry_failure(
            payload, "AUTO_LAND_REQUESTED", "state_source_stale")
        with self.assertRaises(AssertionError):
            self.probe(self.reason(diagnostic.replace("state_source_age_s=3.0", "state_source_age_s=0.1"))).expect_telemetry_failure(
                payload, "AUTO_LAND_REQUESTED", "state_source_stale")
        denied = self.reason(self.diagnostics(), "AUTO_LAND_REQUEST_FAILED")
        self.probe(denied).expect_telemetry_failure(payload, "AUTO_LAND_REQUEST_FAILED", "stale_odom")

    def test_graph_gate_checks_namespace_boundary(self):
        probe = self.module.Probe.__new__(self.module.Probe)
        probe.event = lambda *args: None
        for resource in ("/qualification/fcu/state", "/qualification", "/rosout"):
            self.rospy.get_master = lambda resource=resource: Master([[(resource, ["/qualification/executor"])], [], []])
            probe.graph_gate()
        for resource in ("/qualification-escape", "/other/fcu/state"):
            self.rospy.get_master = lambda resource=resource: Master([[(resource, ["/qualification/executor"])], [], []])
            with self.subTest(resource=resource), self.assertRaises(AssertionError):
                probe.graph_gate()

    def test_main_rejects_nonempty_isolated_master_before_constructing_probe(self):
        self.rospy.get_master = lambda: Master([[("/foreign", ["/other/node"])], [], []])
        with patch.dict(os.environ, {"ROS_MASTER_URI": "http://127.0.0.1:11321"}), \
             patch.object(sys, "argv", ["probe", "--executor", "unused", "--output", "unused"]), \
             patch.object(self.module, "Probe", side_effect=AssertionError("must not start")) as constructor:
            with self.assertRaisesRegex(RuntimeError, "isolated master is not empty"):
                self.module.main()
            constructor.assert_not_called()

    def test_mock_odom_reports_arrival_yaw_and_invalid_orientation(self):
        probe = self.module.Probe.__new__(self.module.Probe)
        probe.state_enabled = False
        probe.odom_enabled = True
        probe.position = (0.7, -0.3, 0.6)
        probe.yaw = 0.4
        published = []
        probe.odom_pub = types.SimpleNamespace(publish=published.append)
        def odom():
            return types.SimpleNamespace(header=types.SimpleNamespace(stamp=None),
                pose=types.SimpleNamespace(pose=types.SimpleNamespace(
                    position=types.SimpleNamespace(x=0, y=0, z=0),
                    orientation=types.SimpleNamespace(x=0, y=0, z=0, w=0))))
        with patch.object(self.rospy, "Time", types.SimpleNamespace(now=lambda: 100), create=True), \
             patch.object(self.module, "Odometry", side_effect=odom):
            probe.bad_odom = False
            probe.telemetry(None)
            self.assertAlmostEqual(published[-1].pose.pose.orientation.z, math.sin(0.2))
            self.assertAlmostEqual(published[-1].pose.pose.orientation.w, math.cos(0.2))
            probe.bad_odom = True
            probe.yaw = 0.0
            probe.telemetry(None)
            self.assertEqual(published[-1].pose.pose.orientation.w, 0.0)

    def test_start_fixture_contains_all_live_parameter_groups(self):
        source = inspect.getsource(self.module.Probe.start)
        for key in ("safety/enabled", "land/return_pos", "land/return_yaw",
                    "cam2body_R", "cam2body_T"):
            with self.subTest(key=key):
                self.assertIn(key, source)
        for fragment in (
                'for color, zone in (("red", "A"), ("purple", "B"), ("blue", "C")):',
                'params["balloon_color_" + color] = zone',
                'params["balloon_zone_" + zone + "/approach_pos"]',
                'params["balloon_zone_" + zone + "/goal"]',
                'params["balloon_zone_" + zone + "/yaw"]'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_normal_land_requires_configured_position_and_yaw_before_mode(self):
        probe = self.module.Probe.__new__(self.module.Probe)
        starts = []
        probe.start = lambda name, **kwargs: starts.append((name, kwargs))
        probe.armed = False
        probe.targets = [(1, {"mask": 3064, "position": [0.3, 0.7, 0.6],
                              "yaw": 0.4 + math.pi / 2.0})]
        probe.modes = []
        probe.arms = []
        probe.statuses = []
        probe.settle = lambda *args: None
        def request(command):
            self.assertEqual((probe.mode, probe.armed), ("OFFBOARD", True))
            self.assertEqual(command, "land")
            return {"request_id": "land"}
        probe.request = request
        probe.expect = lambda *args: None
        def wait(predicate):
            if predicate():
                return True
            probe.modes.append((2, "AUTO.LAND"))
            return predicate() or self.fail("landing condition did not hold")
        probe.wait = wait
        probe.landing(False)
        self.assertEqual(probe.position, (0.7, -0.3, 0.6))
        self.assertEqual(probe.yaw, 0.4)
        self.assertEqual(starts, [("normal-land", {"command_timeout": 12.0})])
        probe.targets[0][1]["yaw"] = math.pi / 2.0
        probe.modes.clear()
        with self.assertRaises(AssertionError):
            probe.landing(False)
        probe.targets[0][1]["yaw"] = 0.4 + math.pi / 2.0
        probe.targets[0][1]["position"] = [0.7, -0.3, 0.6]
        probe.modes.clear()
        with self.assertRaises(AssertionError):
            probe.landing(False)


if __name__ == "__main__":
    unittest.main()
