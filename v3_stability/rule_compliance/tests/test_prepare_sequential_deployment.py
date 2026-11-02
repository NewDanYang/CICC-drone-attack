#!/usr/bin/env python3
"""Offline checks for the local-only sequential deployment manifest tool."""
import importlib.util
import itertools
import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "prepare_sequential_deployment.py"
spec = importlib.util.spec_from_file_location("prepare_sequential_deployment", TOOL)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

PLUGIN_TARGETS = ("wait_for_stable_position", "visual_servo", "goto", "planning_control", "target_tracker")


class PrepareSequentialDeploymentTests(unittest.TestCase):
    def test_candidate_manifest_contains_only_release_payloads(self):
        result = module.prepare()
        payloads = result["payload_sha256"]
        self.assertTrue(result["local_candidate_checks_passed"])
        self.assertFalse(result["deployment_ready"])
        self.assertFalse(result["deployment_performed"])
        self.assertEqual(
            set(payloads),
            {
                "v1_safety_recovery/src/mission_pkg/src/mavros_cnt.cpp",
                "v1_safety_recovery/src/mission_pkg/include/mavros_cnt.h",
                "v3_stability/rule_compliance/deploy/bt_ros.cpp",
                "v3_stability/rule_compliance/deploy/balloon_entry.launch",
                "v3_stability/rule_compliance/deploy/sequence_session.hpp",
                "v3_stability/rule_compliance/deploy/mission_once.py",
                "v3_stability/rule_compliance/tools/start_qualification_nodes.sh",
                "v3_stability/rule_compliance/tools/run_live_diagnostic.py",
                "v3_stability/rule_compliance/tools/qualify_sequential_ros.py",
                "v3_stability/rule_compliance/tools/prepare_sequential_deployment.py",
                "v3_stability/rule_compliance/tools/audit_trial_runtime.py",
                "v3_stability/rule_compliance/tools/analyze_sequential_timing.py",
                "v3_stability/rule_compliance/tools/verify_sequential_offline.py",
                "v2_time_optimization/working_source/src/mission_pkg/src/nodes/action/wait_for_stable_position.cpp",
                "v2_time_optimization/working_source/src/mission_pkg/include/nodes/action/wait_for_stable_position.h",
                "v3_stability/rule_compliance/deploy/visual_servo.cpp",
                "v3_stability/rule_compliance/deploy/visual_servo.h",
                "v3_stability/rule_compliance/deploy/target_tracker.cpp",
                "v3_stability/rule_compliance/deploy/target_tracker.h",
                "v3_stability/rule_compliance/deploy/goto.cpp",
                "v3_stability/rule_compliance/deploy/goto.h",
                "v3_stability/rule_compliance/deploy/goto_ramp.hpp",
                "v3_stability/rule_compliance/deploy/planning_control.cpp",
                "v3_stability/rule_compliance/deploy/planning_control.h",
            },
        )
        self.assertIn("frozen_v2_deployed_controller_baseline", result["source_correspondence"])
        self.assertNotIn("pr4_controller_source", result["source_correspondence"])
        self.assertNotIn("historical_deployed_mission_script_snapshot", payloads)

    def test_new_action_plugins_use_reviewed_deploy_payloads(self):
        expected = {
            "src/nodes/action/goto.cpp": module.DEPLOY / "goto.cpp",
            "include/nodes/action/goto.h": module.DEPLOY / "goto.h",
            "include/nodes/action/goto_ramp.hpp": module.DEPLOY / "goto_ramp.hpp",
            "src/nodes/action/planning_control.cpp": module.DEPLOY / "planning_control.cpp",
            "include/nodes/action/planning_control.h": module.DEPLOY / "planning_control.h",
        }
        for destination, source in expected.items():
            with self.subTest(destination=destination):
                self.assertEqual(module.PLUGIN_PAYLOADS[destination], source)

    def test_protocol_contract_matches_sequential_client_and_controller(self):
        result = module.prepare()
        check = next(item for item in result["checks"] if item["check"] == "client_controller_protocol_contract")
        self.assertTrue(check["passed"])
        self.assertFalse(result["deployment_ready"])
        self.assertIn("/mission_request", result["protocol_contract"]["contract"]["request_topic"])
        self.assertIn("/mission_status", result["protocol_contract"]["contract"]["status_topic"])
        self.assertIn("/mission_abort", result["protocol_contract"]["contract"]["abort_topic"])

    def test_protocol_contract_rejects_topic_strings_without_publishers_or_subscribers(self):
        with tempfile.TemporaryDirectory(dir=module.ROOT) as directory:
            path = Path(directory) / "mission_once.py"
            path.write_text('print("/mission_request /mission_status /mission_ready /mission_abort")', encoding="utf-8")
            with patch.dict(module.PAYLOADS, {"mission_once.py": path}):
                result = module.prepare()
        check = next(item for item in result["checks"] if item["check"] == "client_controller_protocol_contract")
        self.assertFalse(check["passed"])
        self.assertFalse(result["local_candidate_checks_passed"])

    def test_protocol_request_status_fixture_round_trip(self):
        contract = {
            "protocol": 1,
            "server_epoch": "epoch-test",
            "session_id": "session-test",
            "request_id": "request-test",
            "command": "takeoff",
        }
        controller_response = {
            "protocol": contract["protocol"],
            "server_epoch": contract["server_epoch"],
            "session_id": contract["session_id"],
            "request_id": contract["request_id"],
            "status": "ACCEPTED",
        }
        request_required = set(module.prepare()["protocol_contract"]["contract"]["required_request_fields"])
        status_required = set(module.prepare()["protocol_contract"]["contract"]["required_status_fields"])
        self.assertEqual(request_required, contract.keys())
        self.assertTrue(status_required.issubset(controller_response))
        self.assertEqual(contract["request_id"], controller_response["request_id"])

    def test_manifest_hash_comparison_rejects_mismatch_and_escape(self):
        relative = "v3_stability/rule_compliance/deploy/sequence_session.hpp"
        actual = module.sha256(module.ROOT / relative)
        self.assertTrue(module.check_manifest(Path("manifest.json"), {relative: actual})[1]["passed"])
        self.assertFalse(module.check_manifest(Path("manifest.json"), {relative: "0" * 64})[1]["passed"])
        escaped = module.check_manifest(Path("manifest.json"), {"../outside": "0" * 64})[1]
        self.assertFalse(escaped["passed"])
        self.assertEqual(escaped["check"], "manifest_path")

    def test_manifest_requires_exact_complete_release_identity(self):
        manifest = module.prepare()["payload_sha256"]
        self.assertTrue(all(x["passed"] for x in module.check_manifest(Path("manifest.json"), manifest)))
        for incomplete in ({}, dict(list(manifest.items())[:-1])):
            self.assertFalse(module.check_manifest(Path("manifest.json"), incomplete)[0]["passed"])
        extra = dict(manifest, unrelated="0" * 64)
        self.assertFalse(module.check_manifest(Path("manifest.json"), extra)[0]["passed"])

    def test_balloon_timeout_is_not_masked_as_success(self):
        source = (module.DEPLOY / "bt_ros.cpp").read_text(encoding="utf-8")
        balloon = source[source.index('// ---- hit_balloon:'):source.index('// ---- land ----')]
        self.assertIn('Timeout msec=', balloon)
        self.assertNotIn('ForceSuccess', balloon)
        self.assertIn('ATTEMPTED_UNVERIFIED', source)
        self.assertIn('(zone != "A" && !nh->hasParam(param_prefix + "/yaw"))', balloon)
        self.assertIn('zone == "A" ? "" : " yaw=', balloon)
        self.assertIn('filter_window_size=\\"1\\"', balloon)
        self.assertIn('yaw_feedforward_gain=\\"0.0\\"', balloon)
        self.assertIn('getDbl("visual_servo/forward_velocity", 1.0)', balloon)

    def test_balloon_entry_fragment_restores_historical_coordinates(self):
        params = {p.attrib["name"]: p.attrib["value"]
                  for p in ET.parse(module.DEPLOY / "balloon_entry.launch").getroot()}
        self.assertEqual(params, {
            "balloon_zone_A/approach_pos": "4.3;1.0;0.7",
            "balloon_zone_A/goal": "4.3;1.0;1.0",
            "balloon_zone_B/approach_pos": "4.3;-2.0;0.7",
            "balloon_zone_B/goal": "4.3;-2.0;0.7",
            "balloon_zone_B/yaw": "3.14159",
            "balloon_zone_C/approach_pos": "5.3;1.0;0.7",
            "balloon_zone_C/goal": "5.3;1.0;0.7",
            "balloon_zone_C/yaw": "-1.5708",
        })

    def test_generated_balloon_xml_omits_only_zone_a_yaw(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        zig = module.ROOT / ".local-toolchain/zig-windows-x86_64-0.13.0/zig.exe"
        if compiler:
            compiler_command = [compiler]
        elif zig.is_file():
            compiler_command = [str(zig), "c++"]
        else:
            self.skipTest("C++ compiler unavailable")
        source = (module.DEPLOY / "bt_ros.cpp").read_text(encoding="utf-8")
        block = source[source.index('    // ---- hit_balloon:'):source.index('    // ---- land ----')]
        params = {p.attrib["name"]: p.attrib["value"]
                  for p in ET.parse(module.DEPLOY / "balloon_entry.launch").getroot()}
        params.update(balloon_color_red="A", balloon_color_purple="B", balloon_color_blue="C")
        entries = ",".join("{" + json.dumps(k) + "," + json.dumps(v) + "}" for k, v in params.items())
        harness = '''#include <string>
#include <map>
#include <stdexcept>
#include <iostream>
#define ROS_INFO(...) ((void)0)
struct Params {
  std::map<std::string, std::string> values;
  bool hasParam(std::string k) { return values.count(k); }
  bool getParam(std::string k, std::string& v) {
    if (!hasParam(k)) return false;
    v = values.at(k); return true;
  }
};
std::string generate(std::string cmd, Params* nh) {
  bool offline = false;
  auto getStr = [&](std::string k, std::string fallback) {
    return nh->hasParam(k) ? nh->values.at(k) : fallback;
  };
  auto getDbl = [&](std::string k, double fallback) {
    return nh->hasParam(k) ? std::stod(nh->values.at(k)) : fallback;
  };
''' + block + '\nthrow std::runtime_error("unhandled");\n}\n'
        harness += 'int main(int argc, char** argv) { Params p{{' + entries + '}};\n'
        harness += 'if(argc > 2) p.values.erase(argv[2]); try { std::cout << generate(argv[1], &p); } catch(const std::exception&) { return 2; }}\n'
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "entry.cpp"
            binary = Path(directory) / "entry.exe"
            cpp.write_text(harness, encoding="utf-8")
            built = subprocess.run(compiler_command + ["-std=c++17", str(cpp), "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            for color, zone in (("red", "A"), ("purple", "B"), ("blue", "C")):
                completed = subprocess.run([str(binary), "hit_balloon:" + color], capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                xml = ET.fromstring("<Sequence>" + completed.stdout + "</Sequence>")
                self.assertEqual(xml.find("GoTo").attrib["goal"], params[f"balloon_zone_{zone}/goal"])
                self.assertEqual("yaw" in xml.find("GoTo").attrib, zone != "A")
                if zone != "A":
                    missing = subprocess.run([str(binary), "hit_balloon:" + color, f"balloon_zone_{zone}/yaw"], capture_output=True, timeout=10)
                    self.assertEqual(missing.returncode, 2)

    def test_balloon_entry_staging_preserves_launch_bytes_and_backups(self):
        original = module.PR4_LAUNCH.read_bytes()
        # Exercise BOM, CRLF, single quotes, and non-ASCII comments together.
        body = original[3:] if original.startswith(b"\xef\xbb\xbf") else original
        original = b"\xef\xbb\xbf" + body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        original = original.replace(b'name="balloon_zone_A/goal"', b"name='balloon_zone_A/goal'")
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "CMakeLists.txt").write_text("add_executable(bt_ros src/bt_ros.cpp)\n")
            launch = package / "launch/llm_mission.launch"
            launch.parent.mkdir()
            launch.write_bytes(original)
            module.stage_plugins(package)
            first = launch.read_bytes()
            module.stage_plugins(package)
            self.assertEqual(first, launch.read_bytes())
            backups = list(launch.parent.glob("llm_mission.launch.bak_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertTrue(first.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b'balloon_zone_A/yaw', first)
            self.assertIn(b"name='balloon_zone_A/goal'", first)
            self.assertEqual(first.count(b'<include file="$(find mission_pkg)/launch/balloon_entry.launch"/>'), 1)
            self.assertEqual((launch.parent / "balloon_entry.launch").read_bytes(),
                             (module.DEPLOY / "balloon_entry.launch").read_bytes())
            before_lines = original.splitlines(keepends=True)
            after_lines = first.splitlines(keepends=True)
            for line in before_lines:
                if b"balloon_zone_" not in line and b"</launch>" not in line:
                    self.assertIn(line, after_lines)
            ET.fromstring(first)

    def test_stage_plugins_preserves_existing_target_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            cmake = package / "CMakeLists.txt"
            original = "add_executable(bt_ros src/bt_ros.cpp)\n"
            cmake.write_text(original, encoding="utf-8")
            old_source = package / "src/nodes/action/visual_servo.cpp"
            old_source.parent.mkdir(parents=True)
            old_source.write_text("old servo", encoding="utf-8")
            module.stage_plugins(package)
            first_cmake = cmake.read_bytes()
            module.stage_plugins(package)
            self.assertEqual(cmake.read_bytes(), first_cmake)
            self.assertTrue(first_cmake.decode().startswith(original))
            self.assertEqual(first_cmake.decode().count(module.PLUGIN_CMAKE), 1)
            self.assertIn('PROPERTIES PREFIX ""', first_cmake.decode())
            self.assertIn("BT_PLUGIN_EXPORT", first_cmake.decode())
            self.assertIn(f"add_dependencies(bt_ros {' '.join(PLUGIN_TARGETS)})", first_cmake.decode())
            self.assertEqual(len(list(package.glob("CMakeLists.txt.bak_*"))), 1)
            self.assertEqual(len(list(old_source.parent.glob("visual_servo.cpp.bak_*"))), 1)
            for destination, source in {**module.PLUGIN_PAYLOADS,
                                        "src/bt_ros.cpp": module.DEPLOY / "bt_ros.cpp",
                                        "include/sequence_session.hpp": module.DEPLOY / "sequence_session.hpp"}.items():
                self.assertEqual((package / destination).read_bytes(), source.read_bytes())

    @unittest.skipUnless(shutil.which("cmake"), "CMake is not available")
    def test_staged_plugins_configure_with_missing_or_existing_targets(self):
        generator = "Ninja" if shutil.which("ninja") else "Unix Makefiles"
        make_program = shutil.which("ninja") or shutil.which("make")
        if not make_program:
            self.skipTest("CMake configure requires Ninja or Make")
        for present in itertools.product((False, True), repeat=len(PLUGIN_TARGETS)):
            existing = tuple(target for target, enabled in zip(PLUGIN_TARGETS, present) if enabled)
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                package = Path(directory) / "mission_pkg"
                package.mkdir()
                (package / "stub.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
                original = (
                    "cmake_minimum_required(VERSION 3.16)\n"
                    "project(plugin_staging LANGUAGES CXX)\n"
                    "add_executable(bt_ros stub.cpp)\n"
                    "foreach(dependency behaviortree_cpp mavros_cnt drone_base target_det_base catkin_stub opencv_stub)\n"
                    "  add_library(${dependency} INTERFACE)\n"
                    "endforeach()\n"
                    "set(catkin_LIBRARIES catkin_stub)\n"
                    "set(OpenCV_LIBRARIES opencv_stub)\n"
                )
                for target in existing:
                    original += f"add_library({target} SHARED stub.cpp)\n"
                    original += f'set_target_properties({target} PROPERTIES PREFIX "existing_")\n'
                cmake = package / "CMakeLists.txt"
                cmake.write_text(original, encoding="utf-8")
                module.stage_plugins(package)
                module.stage_plugins(package)
                assertions = (
                    f"set_target_properties(bt_ros {' '.join(PLUGIN_TARGETS)} PROPERTIES LINKER_LANGUAGE CXX)\n"
                    "get_target_property(dependencies bt_ros MANUALLY_ADDED_DEPENDENCIES)\n"
                    f"foreach(plugin {' '.join(PLUGIN_TARGETS)})\n"
                    "  if(NOT plugin IN_LIST dependencies)\n"
                    '    message(FATAL_ERROR "Missing bt_ros dependency: ${plugin}")\n'
                    "  endif()\n"
                    "endforeach()\n"
                )
                for target in PLUGIN_TARGETS:
                    assertions += f"get_target_property(prefix {target} PREFIX)\n"
                    expected_prefix = "existing_" if target in existing else ""
                    assertions += f'if(NOT "${{prefix}}" STREQUAL "{expected_prefix}")\n'
                    assertions += f'  message(FATAL_ERROR "Unexpected prefix for {target}")\nendif()\n'
                    if target not in existing:
                        assertions += f"get_target_property(definitions {target} COMPILE_DEFINITIONS)\n"
                        assertions += 'if(NOT "BT_PLUGIN_EXPORT" IN_LIST definitions)\n'
                        assertions += '  message(FATAL_ERROR "Missing plugin export")\nendif()\n'
                        assertions += f"get_target_property(libraries {target} LINK_LIBRARIES)\n"
                        assertions += "foreach(dependency behaviortree_cpp mavros_cnt drone_base target_det_base catkin_stub opencv_stub)\n"
                        assertions += "  if(NOT dependency IN_LIST libraries)\n"
                        assertions += '    message(FATAL_ERROR "Missing plugin link: ${dependency}")\n'
                        assertions += "  endif()\nendforeach()\n"
                cmake.write_text(cmake.read_text(encoding="utf-8") + assertions, encoding="utf-8")
                completed = subprocess.run(
                    [shutil.which("cmake"), "-S", str(package), "-B", str(Path(directory) / "build"),
                     "-G", generator, f"-DCMAKE_MAKE_PROGRAM={make_program}"],
                    capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_staging_replaces_shadowing_source_header_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "CMakeLists.txt").write_text("add_executable(bt_ros src/bt_ros.cpp)\n")
            (package / "src").mkdir()
            shadow = package / "src/sequence_session.hpp"
            shadow.write_bytes(b"old source-adjacent header")
            module.stage_plugins(package)
            self.assertEqual(shadow.read_bytes(), module.DEPLOY.joinpath("sequence_session.hpp").read_bytes())
            backups = list(shadow.parent.glob("sequence_session.hpp.bak_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old source-adjacent header")

    def test_stage_plugins_rejects_unknown_build_before_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "CMakeLists.txt").write_text("project(other)", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lacks bt_ros"):
                module.stage_plugins(package)
            self.assertFalse((package / "src").exists())

    def test_manifest_mismatch_prevents_staging_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            cmake = package / "CMakeLists.txt"
            cmake.write_text("add_executable(bt_ros src/bt_ros.cpp)\n", encoding="utf-8")
            before = cmake.read_bytes()
            manifest = package / "expected.json"
            manifest.write_text(json.dumps({"v3_stability/rule_compliance/deploy/bt_ros.cpp": "0" * 64}), encoding="utf-8")
            with patch("sys.argv", [str(TOOL), "--expected-manifest", str(manifest),
                                    "--stage-plugin-package", str(package)]):
                with self.assertRaises(SystemExit):
                    module.main()
            self.assertEqual(cmake.read_bytes(), before)
            self.assertFalse((package / "src").exists())

    def test_manifest_serialization_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            manifest = module.prepare()["payload_sha256"]
            target.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), manifest)


if __name__ == "__main__":
    unittest.main()
