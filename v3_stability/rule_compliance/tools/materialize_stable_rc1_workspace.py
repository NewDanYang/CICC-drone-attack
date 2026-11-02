#!/usr/bin/env python3
"""Materialize the RC1 ROS package from repository main plus reviewed PR payloads.

The destination must be an independent overlay. Existing bytes are preserved in
a hash-named backup before repository-owned files are copied over them.
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def copy_tree(source, target):
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--underlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.candidate_root.resolve()
    workspace = args.workspace.resolve()
    package = workspace / "src/mission_pkg"
    detector_target = workspace / "src/object_det"
    if detector_target.exists():
        parser.error("detector destination exists; use a fresh qualification workspace")
    underlay = args.underlay.resolve()
    if workspace == underlay or underlay in workspace.parents or root == workspace or root in workspace.parents:
        parser.error("destination must be independent of the preserved underlay")
    baseline = root / "official_baseline/catkin_ws/src/mission_pkg"
    detector = root / "official_baseline/catkin_ws/src/object_det"
    v2 = root / "v2_time_optimization/working_source/src/mission_pkg"
    safety = root / "v1_safety_recovery/src/mission_pkg"
    launch = root / "v3_stability/hit_balloon_v2/deployed_source/llm_mission.launch"
    required = [root / "v3_stability/rule_compliance/deploy/aruco_detect_node.py",
                detector / "package.xml", detector / "config/detection_params.yaml",
                detector / "scripts/det_color_conda.sh",
                root / "v3_stability/rule_compliance/deploy/det_color.py",
                baseline / "CMakeLists.txt", baseline / "package.xml",
                launch, safety / "src/mavros_cnt.cpp", safety / "include/mavros_cnt.h",
                v2 / "src/nodes/action/wait_for_stable_position.cpp",
                v2 / "include/nodes/action/wait_for_stable_position.h"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("missing repository material: " + ", ".join(missing))

    backup = None
    if package.exists():
        old_hash = hashlib.sha256()
        for path in sorted(package.rglob("*")):
            if path.is_file():
                old_hash.update(str(path.relative_to(package)).encode())
                old_hash.update(path.read_bytes())
        backup_root = workspace / "rc1_source_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / ("mission_pkg_" + old_hash.hexdigest()[:12])
        if backup.exists():
            parser.error("backup already exists; inspect before repeating materialization")
    stage = workspace / "rc1_materializing"
    if stage.exists():
        parser.error("unfinished materialization directory exists; inspect it first")
    stage.mkdir(parents=True)
    copy_tree(baseline, stage)
    overlays = {
        "launch/llm_mission.launch": launch,
        "scripts/aruco_detect_node.py": root / "v3_stability/rule_compliance/deploy/aruco_detect_node.py",
        "src/mavros_cnt.cpp": safety / "src/mavros_cnt.cpp",
        "include/mavros_cnt.h": safety / "include/mavros_cnt.h",
        "src/nodes/action/wait_for_stable_position.cpp": v2 / "src/nodes/action/wait_for_stable_position.cpp",
        "include/nodes/action/wait_for_stable_position.h": v2 / "include/nodes/action/wait_for_stable_position.h",
    }
    for relative, source in overlays.items():
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    # Rename on the same filesystem; no old server-only source survives in src.
    package.parent.mkdir(parents=True, exist_ok=True)
    if backup:
        package.rename(backup)
    stage.rename(package)

    # Materialize the reviewed detector into the same overlay.
    if detector.is_dir():
        detector_stage = workspace / "rc1_detector_materializing"
        if detector_stage.exists():
            parser.error("unfinished detector materialization directory exists; inspect it first")
        detector_stage.mkdir(parents=True)
        copy_tree(detector, detector_stage)
        shutil.copy2(root / "v3_stability/rule_compliance/deploy/det_color.py",
                     detector_stage / "scripts/det_color.py")
        for script in (detector_stage / "scripts").glob("*"):
            if script.is_file():
                script.chmod(script.stat().st_mode | 0o111)
        detector_target.parent.mkdir(parents=True, exist_ok=True)
        detector_stage.rename(detector_target)

    for script in (package / "scripts").glob("*.py"):
        script.chmod(script.stat().st_mode | 0o111)

    records = []
    for path in sorted(package.rglob("*")):
        if path.is_file() and ".bak_" not in path.name:
            relative = path.relative_to(package).as_posix()
            source = overlays.get(relative, baseline / relative)
            records.append({"path": relative, "sha256": digest(path),
                            "repository_source": source.relative_to(root).as_posix()})
    result = {
        "schema_version": 1,
        "workspace": str(workspace),
        "package": str(package),
        "detector": str(detector_target) if detector_target.is_dir() else None,
        "detector_repository_source": str(detector.relative_to(root)) if detector.is_dir() else None,
        "detector_files": [{"path": p.relative_to(detector_target).as_posix(),
                            "sha256": digest(p),
                            "repository_source": ("v3_stability/rule_compliance/deploy/det_color.py"
                                if p.relative_to(detector_target).as_posix() == "scripts/det_color.py"
                                else (detector / p.relative_to(detector_target)).relative_to(root).as_posix())}
                           for p in sorted(detector_target.rglob("*"))
                           if p.is_file() and "__pycache__" not in p.parts],
        "detector_model_present": (detector_target / "models/best.pt").is_file(),
        "main_baseline": str(baseline),
        "main_v2_overlay": str(v2),
        "main_overlays": {k: v.relative_to(root).as_posix() for k, v in overlays.items()},
        "backup": str(backup) if backup else None,
        "files": records,
        "research_sources_copied": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"materialized": True, "files": len(records), "backup": str(backup) if backup else None}))


if __name__ == "__main__":
    main()
