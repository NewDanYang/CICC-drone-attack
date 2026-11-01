#!/usr/bin/env python3
"""Prepare a reviewable local manifest for sequential-mission deployment."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PR4 = ROOT / "v3_stability" / "hit_balloon_v2" / "deployed_source"
PR4_LAUNCH = ROOT / "v2_time_optimization" / "working_source" / "src" / "mission_pkg" / "launch" / "llm_mission.launch"
DEPLOY = ROOT / "v3_stability" / "rule_compliance" / "deploy"
LEGACY_DEPLOY = DEPLOY / "deploy_rule_compliance.sh"
PLUGIN_PACKAGE = ROOT / "v2_time_optimization/working_source/src/mission_pkg"
PLUGIN_PAYLOADS = {
    "src/nodes/action/wait_for_stable_position.cpp": PLUGIN_PACKAGE / "src/nodes/action/wait_for_stable_position.cpp",
    "include/nodes/action/wait_for_stable_position.h": PLUGIN_PACKAGE / "include/nodes/action/wait_for_stable_position.h",
    "src/nodes/action/visual_servo.cpp": DEPLOY / "visual_servo.cpp",
    "include/nodes/action/visual_servo.h": DEPLOY / "visual_servo.h",
    "src/nodes/perception/target_tracker.cpp": DEPLOY / "target_tracker.cpp",
    "include/nodes/perception/target_tracker.h": DEPLOY / "target_tracker.h",
    "src/nodes/action/goto.cpp": DEPLOY / "goto.cpp",
    "include/nodes/action/goto.h": DEPLOY / "goto.h",
    "include/nodes/action/goto_ramp.hpp": DEPLOY / "goto_ramp.hpp",
    "src/nodes/action/planning_control.cpp": DEPLOY / "planning_control.cpp",
    "include/nodes/action/planning_control.h": DEPLOY / "planning_control.h",
}
PLUGIN_CMAKE = '''
# Sequential mission runtime dependency (also supports explicit plugin lists).
if(NOT TARGET wait_for_stable_position)
  add_library(wait_for_stable_position SHARED src/nodes/action/wait_for_stable_position.cpp)
  target_compile_definitions(wait_for_stable_position PRIVATE BT_PLUGIN_EXPORT)
  set_target_properties(wait_for_stable_position PROPERTIES PREFIX "")
  target_link_libraries(wait_for_stable_position PRIVATE behaviortree_cpp mavros_cnt drone_base target_det_base ${catkin_LIBRARIES} ${OpenCV_LIBRARIES})
endif()
if(NOT TARGET visual_servo)
  add_library(visual_servo SHARED src/nodes/action/visual_servo.cpp)
  target_compile_definitions(visual_servo PRIVATE BT_PLUGIN_EXPORT)
  set_target_properties(visual_servo PROPERTIES PREFIX "")
  target_link_libraries(visual_servo PRIVATE behaviortree_cpp mavros_cnt drone_base target_det_base ${catkin_LIBRARIES} ${OpenCV_LIBRARIES})
endif()
if(NOT TARGET goto)
  add_library(goto SHARED src/nodes/action/goto.cpp)
  target_compile_definitions(goto PRIVATE BT_PLUGIN_EXPORT)
  set_target_properties(goto PROPERTIES PREFIX "")
  target_link_libraries(goto PRIVATE behaviortree_cpp mavros_cnt drone_base target_det_base ${catkin_LIBRARIES} ${OpenCV_LIBRARIES})
endif()
if(NOT TARGET planning_control)
  add_library(planning_control SHARED src/nodes/action/planning_control.cpp)
  target_compile_definitions(planning_control PRIVATE BT_PLUGIN_EXPORT)
  set_target_properties(planning_control PROPERTIES PREFIX "")
  target_link_libraries(planning_control PRIVATE behaviortree_cpp mavros_cnt drone_base target_det_base ${catkin_LIBRARIES} ${OpenCV_LIBRARIES})
endif()
if(NOT TARGET target_tracker)
  add_library(target_tracker SHARED src/nodes/perception/target_tracker.cpp)
  target_compile_definitions(target_tracker PRIVATE BT_PLUGIN_EXPORT)
  set_target_properties(target_tracker PROPERTIES PREFIX "")
  target_link_libraries(target_tracker PRIVATE behaviortree_cpp mavros_cnt drone_base target_det_base ${catkin_LIBRARIES} ${OpenCV_LIBRARIES})
endif()
add_dependencies(bt_ros wait_for_stable_position visual_servo goto planning_control target_tracker)
'''
PAYLOADS = {
    "bt_ros.cpp": DEPLOY / "bt_ros.cpp",
    "sequence_session.hpp": DEPLOY / "sequence_session.hpp",
    "balloon_entry.launch": DEPLOY / "balloon_entry.launch",
    "mission_once.py": DEPLOY / "mission_once.py",
    "start_qualification_nodes.sh": ROOT / "v3_stability/rule_compliance/tools/start_qualification_nodes.sh",
    "run_live_diagnostic.py": ROOT / "v3_stability/rule_compliance/tools/run_live_diagnostic.py",
    "qualify_sequential_ros.py": ROOT / "v3_stability/rule_compliance/tools/qualify_sequential_ros.py",
    "prepare_sequential_deployment.py": ROOT / "v3_stability/rule_compliance/tools/prepare_sequential_deployment.py",
    "audit_trial_runtime.py": ROOT / "v3_stability/rule_compliance/tools/audit_trial_runtime.py",
    "analyze_sequential_timing.py": ROOT / "v3_stability/rule_compliance/tools/analyze_sequential_timing.py",
    "verify_sequential_offline.py": ROOT / "v3_stability/rule_compliance/tools/verify_sequential_offline.py",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_manifest(path: Path, manifest: dict[str, str]) -> list[dict[str, object]]:
    required = set(prepare()["payload_sha256"])
    results = [{"check": "manifest_payload_set", "passed": set(manifest) == required,
                "missing": sorted(required - set(manifest)),
                "unexpected": sorted(set(manifest) - required)}]
    for rel_path, expected in manifest.items():
        candidate = (ROOT / rel_path).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            results.append({"check": "manifest_path", "name": rel_path, "passed": False,
                            "detail": "path escapes repository"})
            continue
        actual = sha256(candidate) if candidate.is_file() else None
        results.append({"check": "manifest_sha256", "name": rel_path,
                        "passed": actual == expected, "expected": expected,
                        "actual": actual})
    return results


def balloon_entry_launch_bytes(original: bytes) -> bytes:
    tree = ET.fromstring(original)
    fragment = ET.parse(DEPLOY / "balloon_entry.launch").getroot()
    values = {param.attrib["name"]: param.attrib["value"].encode("ascii")
              for param in fragment.findall("param")}

    def update(match: re.Match[bytes]) -> bytes:
        tag = match.group()
        if tag.startswith(b"<!--"):
            return tag
        name = re.search(rb"\bname\s*=\s*([\"'])(.*?)\1", tag)
        if name is None:
            return tag
        key = name[2].decode("utf-8")
        if key == "balloon_zone_A/yaw":
            return b""
        if key not in values:
            return tag
        return re.sub(rb"(\bvalue\s*=\s*)([\"'])(.*?)\2",
                      lambda value: value[1] + value[2] + values[key] + value[2], tag)

    updated = re.sub(rb"<!--.*?-->|<param\b[^>]*?/>", update, original, flags=re.DOTALL)
    include = "$(find mission_pkg)/launch/balloon_entry.launch"
    if not any(node.attrib.get("file") == include for node in tree.findall("include")):
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        addition = b'    <include file="' + include.encode("ascii") + b'"/>' + newline
        updated, count = re.subn(rb"</launch\s*>", lambda match: addition + match.group(), updated)
        if count != 1:
            raise ValueError("mission launch must have one closing launch tag")
    ET.fromstring(updated)
    return updated


def write_with_backup(target: Path, content: bytes) -> None:
    if target.is_file() and target.read_bytes() != content:
        backup = target.with_name(target.name + ".bak_" + sha256(target)[:12])
        if not backup.exists():
            backup.write_bytes(target.read_bytes())
    target.write_bytes(content)


def stage_plugins(package: Path) -> None:
    """Stage the reviewed plugin pairs into an existing isolated mission_pkg."""
    cmake = package / "CMakeLists.txt"
    original = cmake.read_text(encoding="utf-8-sig")
    if not re.search(r"add_executable\s*\(\s*bt_ros\b", original):
        raise ValueError("mission_pkg CMakeLists.txt lacks bt_ros target")
    launch = package / "launch/llm_mission.launch"
    launch_bytes = balloon_entry_launch_bytes(launch.read_bytes()) if launch.is_file() else None
    package_payloads = {**PLUGIN_PAYLOADS,
                        "launch/balloon_entry.launch": DEPLOY / "balloon_entry.launch",
                        "src/bt_ros.cpp": DEPLOY / "bt_ros.cpp",
                        "include/sequence_session.hpp": DEPLOY / "sequence_session.hpp"}
    # Quoted includes prefer a legacy source-adjacent header over include paths.
    if (package / "src/sequence_session.hpp").exists():
        package_payloads["src/sequence_session.hpp"] = DEPLOY / "sequence_session.hpp"
    for destination, source in package_payloads.items():
        target = package / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_bytes() != source.read_bytes():
            backup = target.with_name(target.name + ".bak_" + sha256(target)[:12])
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
        target.write_bytes(source.read_bytes())
    if launch_bytes is not None:
        write_with_backup(launch, launch_bytes)
    if PLUGIN_CMAKE not in original:
        backup = cmake.with_name("CMakeLists.txt.bak_" + sha256(cmake)[:12])
        if not backup.exists():
            backup.write_bytes(cmake.read_bytes())
        cmake.write_bytes((original + PLUGIN_CMAKE).encode("utf-8"))


def prepare() -> dict[str, object]:
    checks: list[dict[str, object]] = []
    payloads = {**PAYLOADS, **PLUGIN_PAYLOADS}
    baseline_controller = PR4 / "bt_ros.cpp"
    baseline_mission = PR4 / "mission_once.py"

    records = {}
    for logical_name, path in payloads.items():
        relative = path.relative_to(ROOT).as_posix()
        exists = path.is_file()
        checks.append({"check": "payload_present", "name": logical_name, "path": relative,
                       "passed": exists})
        if exists:
            records[relative] = sha256(path)

    for field, path, validator, description in (
        ("mission_once.py", PAYLOADS["mission_once.py"], lambda p: ast.parse(p.read_text(encoding="utf-8")), "Python syntax"),
        ("pr4_llm_mission.launch", PR4_LAUNCH, lambda p: ET.parse(p), "launch XML"),
        ("balloon_entry.launch", DEPLOY / "balloon_entry.launch", lambda p: ET.parse(p), "balloon entry XML"),
    ):
        if not path.is_file():
            checks.append({"check": field, "passed": False, "detail": f"{description} missing"})
            continue
        try:
            validator(path)
            passed, detail = True, f"{description} parsed"
        except (SyntaxError, UnicodeDecodeError, ET.ParseError) as exc:
            passed, detail = False, str(exc)
        checks.append({"check": field, "passed": passed, "detail": detail})

    source_labels = {
        "frozen_v2_deployed_controller_baseline": baseline_controller,
        "staged_deployment_controller": PAYLOADS["bt_ros.cpp"],
        "historical_deployed_mission_script_snapshot": baseline_mission,
    }
    correspondence = {}
    for label, path in source_labels.items():
        correspondence[label] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path) if path.is_file() else None,
        }
    checks.append({
        "check": "controller_source_correspondence",
        "passed": all(value["sha256"] for value in correspondence.values()),
        "detail": "hashes identify the frozen deployed baseline, staged candidate, and historical mission snapshot",
    })

    controller_text = PAYLOADS["bt_ros.cpp"].read_text(encoding="utf-8") if PAYLOADS["bt_ros.cpp"].is_file() else ""
    client_text = PAYLOADS["mission_once.py"].read_text(encoding="utf-8") if PAYLOADS["mission_once.py"].is_file() else ""
    protocol_contract = {
        "request_topic": "/mission_request",
        "status_topic": "/mission_status",
        "ready_topic": "/mission_ready",
        "abort_topic": "/mission_abort",
        "required_request_fields": ("protocol", "server_epoch", "session_id", "request_id", "command"),
        "required_status_fields": ("protocol", "server_epoch", "session_id", "request_id", "status"),
        "required_ready_fields": ("protocol", "server_epoch", "session_id", "status", "state"),
    }
    controller_requirements = (
        'advertise<std_msgs::String>("/mission_status"',
        'advertise<std_msgs::String>("/mission_ready"',
        'nh.subscribe("/mission_request"',
        'nh.subscribe("/mission_abort"',
        'payload.at("server_epoch")',
        'payload.at("session_id")',
        'payload.at("request_id")',
        'payload.at("command")',
        '"status", "READY"',
    )
    client_requirements = (
        'Publisher("/mission_request"',
        'Publisher("/mission_abort"',
        'Subscriber("/mission_ready"',
        'Subscriber("/mission_status"',
        '"request_id"',
        '"server_epoch"',
        '"session_id"',
        '"command"',
    )
    contract_passed = (
        all(fragment in controller_text for fragment in controller_requirements)
        and all(fragment in client_text for fragment in client_requirements)
    )
    checks.append({"check": "client_controller_protocol_contract", "passed": contract_passed,
                   "detail": "both client and controller must implement matching request, status, abort topics and protocol fields"})
    result_contract = {"contract": protocol_contract, "passed": contract_passed}

    legacy_text = LEGACY_DEPLOY.read_text(encoding="utf-8") if LEGACY_DEPLOY.is_file() else ""
    legacy_pins = re.findall(r'"mission_once\.py\|[^|]+\|([0-9a-f]{32})\|([0-9a-f]{32})"', legacy_text)
    candidate_md5 = hashlib.md5(PAYLOADS["mission_once.py"].read_bytes()).hexdigest() if PAYLOADS["mission_once.py"].is_file() else None
    legacy_covers_all = False
    checks.append({
        "check": "legacy_deployer_compatible",
        "passed": bool(legacy_pins and candidate_md5 in legacy_pins[0] and legacy_covers_all),
        "detail": "legacy script is historical and does not stage the PR4 controller/header/launch; do not use for this package",
    })
    return {
        "mode": "local_prepare_only",
        "deployment_performed": False,
        "local_candidate_checks_passed": not any(item.get("passed") is False for item in checks if item["check"] != "legacy_deployer_compatible"),
        "deployment_ready": False,
        "payload_sha256": records,
        "source_correspondence": correspondence,
        "plugin_staging_map": {destination: source.relative_to(ROOT).as_posix()
                               for destination, source in PLUGIN_PAYLOADS.items()},
        "plugin_cmake_integration": PLUGIN_CMAKE,
        "protocol_contract": result_contract,
        "checks": checks,
        "required_target_gates": [
            "confirm live target hashes and record timestamped backups before copying",
            "confirm no formal-trial lock and verify flight-controller armed state is false",
            "copy every payload listed in payload_sha256 as one reviewed release set",
            "stage all four reviewed plugin source/header pairs and their helper headers with --stage-plugin-package into the isolated mission_pkg; regenerate CMake after build_candidate.sh has generated its CMakeLists.txt",
            "require isolated mission_pkg/launch/llm_mission.launch to include balloon_entry.launch before runtime; --stage-plugin-package updates an existing launch with byte-preserving balloon-only changes and backups",
            "run catkin_make --force-cmake --pkg mission_pkg -j4 in the target ROS workspace and record exit status plus changed object/link outputs",
            "run bt_ros --check-plugins with the isolated overlay first in CMAKE_PREFIX_PATH; require sequential_plugin_preflight_passed=1 before starting simulation; normal startup must validate all live-parameter trees before READY",
            "after confirmed disarm, deliberately stop only the owned qualification graph, run preflight, then restart that graph once; verify runtime PID/binary hashes, session reset, ordering, abort and landing; never kill/restart only its supervised mission node",
            "if target build or smoke verification fails, restore source backups and rebuild before restarting",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-manifest", type=Path,
                        help="write generated local SHA-256 manifest JSON")
    parser.add_argument("--expected-manifest", type=Path,
                        help="compare payload bytes to a reviewed SHA-256 JSON object")
    parser.add_argument("--stage-plugin-package", type=Path,
                        help="stage reviewed plugins and CMake integration into an existing isolated mission_pkg")
    args = parser.parse_args()

    result = prepare()
    if args.expected_manifest:
        manifest = json.loads(args.expected_manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in manifest.items()):
            parser.error("expected manifest must map repository-relative paths to SHA-256 strings")
        extra = check_manifest(args.expected_manifest, manifest)
        result["checks"].extend(extra)
        result["local_candidate_checks_passed"] = result["local_candidate_checks_passed"] and not any(
            item.get("passed") is False for item in extra if item["check"] != "legacy_deployer_compatible"
        )
    if args.stage_plugin_package:
        package = args.stage_plugin_package.resolve()
        if package == Path("/home/ubuntu/catkin_ws/src/mission_pkg").resolve() or package == PLUGIN_PACKAGE.resolve() or package == (ROOT / "official_baseline/catkin_ws/src/mission_pkg").resolve():
            parser.error("refusing to stage into a frozen source snapshot")
        if not result["local_candidate_checks_passed"]:
            parser.error("candidate checks failed; refusing plugin staging")
        stage_plugins(package)
        result["plugins_staged_at"] = str(package)
    if args.write_manifest:
        args.write_manifest.write_text(json.dumps(result["payload_sha256"], indent=2) + "\n", encoding="utf-8")
        result["manifest_written"] = str(args.write_manifest)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["local_candidate_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
