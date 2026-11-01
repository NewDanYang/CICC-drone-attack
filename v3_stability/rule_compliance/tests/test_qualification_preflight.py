import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "start_qualification_nodes.sh"
BASH = (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash"))


@unittest.skipUnless(Path(BASH).is_file(), "Git Bash is required")
class QualificationPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ws = self.root / "qualification_ws"
        self.underlay = self.root / "catkin_ws"
        self.px4 = self.root / "PX4PSP"
        self.state = self.root / "state"
        self.marker = self.root / "wrapper-called"
        self.source = self.root / "candidate.py"
        self.source.write_text("print('candidate')\n", encoding="utf-8")
        self._file(self.ws / "src/mission_pkg/scripts/aruco_detect_node.py", "old\n")
        for path in (
            self.ws / "src/mission_pkg/launch/llm_mission.launch",
            self.ws / "src/mission_pkg/launch/aruco_detect.launch",
            self.underlay / "src/object_det/launch/detection_color.launch",
            self.underlay / "src/ego_planner/launch/FS-J310/FS-J310_ego-planner.launch",
        ):
            self._file(path, "<launch/>\n")
        for path in (
            self.ws / "devel/setup.bash", self.underlay / "devel/setup.bash",
            self.underlay / "src/sensor_pkg/main.py",
            self.underlay / "src/sensor_pkg/AgentContestMap.py",
            self.underlay / "src/sensor_pkg/cloud_transform_node.py",
            self.px4 / "SITLRun.sh",
        ):
            self._file(path, "\n")
        self.ros_setup = self.root / "ros/setup.bash"
        self._file(self.ros_setup, "\n")
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self._command("ldd", "exit 0")
        self._command("xdpyinfo", "exit 0")
        self._command("rospack", 'case "$2" in mission_pkg) printf "%s\\n" "$TCEI_WS_ROOT/src/mission_pkg";; *) printf "%s\\n" "$TCEI_UNDERLAY_WS/src/$2";; esac')
        self._command("roslaunch", '[[ "$1" == "--files" ]] || exit 9; case "$2" in object_det) printf "%s\\n" "$TCEI_UNDERLAY_WS/src/object_det/launch/detection_color.launch";; ego_planner) printf "%s\\n" "$TCEI_UNDERLAY_WS/src/ego_planner/launch/FS-J310/FS-J310_ego-planner.launch";; *) exit 9;; esac')
        self._command("df", 'printf "Filesystem 1024-blocks Used Available Capacity Mounted on\\nmock 9999999 1 9999998 1%% /\\n"')
        self.python = self.bin / "python-mock"
        self._command("python-mock", 'if [[ "$1" == "-c" ]]; then exit 0; fi; exec python "$@"')
        self.simulator = self.px4 / "RflySimUE5/RflySim3D/Binaries/Linux/RflySim3D"
        self._file(self.simulator, "#!/usr/bin/env bash\nexit 0\n", executable=True)
        self._file(self.ws / "devel/lib/mission_pkg/bt_ros", '#!/usr/bin/env bash\n[[ "$1" == "--check-plugins" ]] || exit 9\necho sequential_plugin_preflight_passed=1\n', executable=True)
        self.wrapper = self.root / "wrapper.sh"
        self._file(self.wrapper, f'#!/usr/bin/env bash\ntouch "{self.marker.as_posix()}"\n', executable=True)
        self.authority = self.root / "Xauthority"
        self.authority.touch()
        self.env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                        TCEI_WS_ROOT=str(self.ws), TCEI_UNDERLAY_WS=str(self.underlay),
                        TCEI_PX4_ROOT=str(self.px4), TCEI_ROS_SETUP=str(self.ros_setup),
                        TCEI_RFLYSIM_SDK_ROOT=str(self.sdk), TCEI_QUAL_STATE_DIR=str(self.state),
                        TCEI_QUAL_ARUCO_SOURCE=str(self.source),
                        TCEI_QUAL_ARUCO_SHA256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
                        TCEI_SYSTEM_PYTHON=str(self.python), TCEI_SENSOR_PYTHON=str(self.python),
                        TCEI_SIM_WRAPPER=str(self.wrapper), TCEI_LDD=str(self.bin / "ldd"),
                        TCEI_SIM_LOCK_DIR=str(self.root / "sim.lock"),
                        XAUTHORITY=str(self.authority), DISPLAY=":20")

    def _file(self, path, content, executable=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if executable:
            path.chmod(0o755)

    def _command(self, name, body):
        self._file(self.bin / name, "#!/usr/bin/env bash\n" + body + "\n", executable=True)

    def run_launcher(self, mode):
        return subprocess.run([BASH, str(SCRIPT), mode], env=self.env, capture_output=True,
                              text=True, timeout=30)

    def test_preflight_is_read_only_and_start_delegates_once(self):
        result = self.run_launcher("--preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("qualification_preflight_passed=1", result.stdout)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual((self.ws / "src/mission_pkg/scripts/aruco_detect_node.py").read_text(), "old\n")
        start = self.run_launcher("--start")
        self.assertEqual(start.returncode, 0, start.stderr)
        self.assertTrue(self.marker.exists())

    def test_missing_plugin_rejects_before_simulator_start(self):
        self._file(self.ws / "devel/lib/mission_pkg/bt_ros",
                   '#!/usr/bin/env bash\necho "missing WaitForStablePosition"\nexit 1\n', executable=True)
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("mission plugin preflight failed", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_old_binary_without_check_marker_rejects_start(self):
        self._file(self.ws / "devel/lib/mission_pkg/bt_ros", "#!/usr/bin/env bash\nexit 0\n", executable=True)
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("lacks verified plugin preflight", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_bad_hash_rejects_start_before_wrapper(self):
        self.env["TCEI_QUAL_ARUCO_SHA256"] = "0" * 64
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_bad_launch_rejects_start_before_wrapper(self):
        self._file(self.ws / "src/mission_pkg/launch/llm_mission.launch", "<launch>\n")
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.marker.exists())

    def test_nested_ego_launch_is_resolved_before_wrapper(self):
        result = self.run_launcher("--preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.underlay / "src/ego_planner/launch/FS-J310_ego-planner.launch").exists())
        self.assertFalse(self.marker.exists())

    def test_unresolved_ego_launch_rejects_start(self):
        self._command("roslaunch", 'if [[ "$2" == "ego_planner" ]]; then exit 1; fi; printf "%s\\n" "$TCEI_UNDERLAY_WS/src/object_det/launch/detection_color.launch"')
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("cannot resolve ROS launch: ego_planner", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_existing_lock_rejects_start_before_wrapper(self):
        Path(self.env["TCEI_SIM_LOCK_DIR"]).mkdir()
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse(self.marker.exists())

    def test_sensor_import_failure_rejects_start(self):
        self._command("python-mock", 'if [[ "$1" == "-c" ]]; then exit 1; fi; exec python "$@"')
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("sensor/map Python dependencies", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_missing_shared_library_rejects_start(self):
        self._command("ldd", 'printf "libmissing.so => not found\\n"')
        result = self.run_launcher("--start")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("missing shared libraries", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_startup_marker_follows_bounded_graph_and_heartbeat_gate(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(source.index("ready_deadline=$((SECONDS +"), source.index("qualification_nodes_started=1"))
        self.assertLess(source.index("check_graph && timeout"), source.index("qualification_nodes_started=1"))
        self.assertIn('json.loads(m.data).get("state") == "IDLE"', source)
        self.assertIn('m.connected and not m.armed and 0 <= age <= 2.5', source)


if __name__ == "__main__":
    unittest.main()
