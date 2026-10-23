#!/usr/bin/env python3
"""MD5-gated, byte-preserving candidate 2 deployment and rollback."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


MARKER = "time_opt_candidate2"
OLD_DELAY_DECL = "        std::string delay     = std::to_string((int)getDbl(\"cross_frame/observe_delay_ms\", 2000));"
OLD_DELAY_XML = (
    '            "      <Delay delay_msec=\\\"" + delay + "\\\">\\n"\n'
    '            "        <AlwaysSuccess/>\\n"\n'
    '            "      </Delay>\\n"\n'
)
NEW_STABLE_DECL = (
    "        std::string stable_pos_threshold =\n"
    "            std::to_string(getDbl(\"optimization/position_threshold\", 0.15));\n"
    "        std::string stable_vel_threshold =\n"
    "            std::to_string(getDbl(\"optimization/velocity_threshold\", 0.08));\n"
    "        std::string stable_confirm_time =\n"
    "            std::to_string(getDbl(\"optimization/stable_confirm_time\", 0.50));\n"
    "        std::string stable_timeout =\n"
    "            std::to_string(getDbl(\"optimization/settle_timeout\",\n"
    "                                  getDbl(\"cross_frame/observe_delay_ms\", 2000) / 1000.0));"
)
NEW_STABLE_XML = (
    '            "      <!-- wait for position and velocity stability; keep the 2 s cap -->\\n"\n'
    '            "      <WaitForStablePosition goal=\\\"" + observe + "\\\" "\n"\n'
    '            "position_threshold=\\\"" + stable_pos_threshold + "\\\" "\n"\n'
    '            "velocity_threshold=\\\"" + stable_vel_threshold + "\\\" "\n"\n'
    '            "stable_confirm_time=\\\"" + stable_confirm_time + "\\\" "\n"\n'
    '            "timeout=\\\"" + stable_timeout + "\\\"/>\\n"\n'
)


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def backup(path: Path) -> Path:
    target = path.with_name(path.name + ".bak_" + MARKER)
    if target.exists():
        raise SystemExit(f"backup already exists: {target}")
    shutil.copy2(path, target)
    return target


def patch_text(path: Path, old: str, new: str) -> tuple[str, str]:
    before = path.read_text(encoding="utf-8")
    if "WaitForStablePosition" in before:
        raise SystemExit(f"{path} already contains WaitForStablePosition; refusing a second patch")
    if before.count(old) != 1:
        raise SystemExit(f"expected text is not unique in {path}")
    after = before.replace(old, new)
    path.write_text(after, encoding="utf-8", newline="")
    return hashlib.md5(before.encode("utf-8")).hexdigest(), digest(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bt", type=Path, default=Path("/home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp"))
    parser.add_argument("--launch", type=Path, default=Path("/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch"))
    parser.add_argument("--node-header", type=Path, default=Path("/home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/action/wait_for_stable_position.h"))
    parser.add_argument("--node-source", type=Path, default=Path("/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/wait_for_stable_position.cpp"))
    parser.add_argument("--header-payload", type=Path, required=True)
    parser.add_argument("--source-payload", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("/home/ubuntu/tcei_baseline_tools/time_optimization/candidate2_manifest.json"))
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    paths = [args.bt, args.launch]
    backups = {str(path): path.with_name(path.name + ".bak_" + MARKER) for path in paths}

    if args.rollback:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = Path(item["path"])
            backup_path = Path(item["backup"])
            if digest(path) != item["after_md5"] or digest(backup_path) != item["before_md5"]:
                raise SystemExit(f"MD5 mismatch; refusing candidate 2 rollback for {path}")
            shutil.copy2(backup_path, path)
        for item in manifest["added_files"]:
            path = Path(item["path"])
            if path.exists() and digest(path) != item["md5"]:
                raise SystemExit(f"added file changed; refusing candidate 2 rollback for {path}")
            if path.exists():
                path.unlink()
        print(json.dumps({"rolled_back": True, "files": manifest["files"]}, indent=2))
        return

    if args.manifest.exists():
        raise SystemExit("candidate 2 manifest already exists")
    for path in (args.bt, args.launch):
        if not path.is_file():
            raise SystemExit(f"missing source file: {path}")
    if args.node_header.exists() or args.node_source.exists():
        raise SystemExit("candidate 2 node file already exists; inspect before patching")
    for payload in (args.header_payload, args.source_payload):
        if not payload.is_file():
            raise SystemExit(f"missing payload: {payload}")

    bt_text = args.bt.read_text(encoding="utf-8")
    if "WaitForStablePosition" in bt_text:
        raise SystemExit("candidate 2 already appears in bt_ros.cpp")
    if bt_text.count(OLD_DELAY_DECL) != 1 or bt_text.count(OLD_DELAY_XML) != 1:
        raise SystemExit("candidate 2 bt_ros.cpp anchors are not unique")
    bt_after = bt_text.replace(OLD_DELAY_DECL, NEW_STABLE_DECL).replace(OLD_DELAY_XML, NEW_STABLE_XML)

    launch_text = args.launch.read_text(encoding="utf-8")
    if "optimization/settle_timeout" in launch_text:
        raise SystemExit("candidate 2 launch parameters already present")
    needle = '<param name="cross_frame/observe_delay_ms"'
    lines = launch_text.splitlines(keepends=True)
    indexes = [index for index, line in enumerate(lines) if needle in line]
    if len(indexes) != 1:
        raise SystemExit("candidate 2 launch anchor is not unique")
    newline = "\r\n" if "\r\n" in launch_text else "\n"
    insertion = (
        f'    <param name="optimization/position_threshold" value="0.15" type="double"/>{newline}'
        f'    <param name="optimization/velocity_threshold" value="0.08" type="double"/>{newline}'
        f'    <param name="optimization/stable_confirm_time" value="0.50" type="double"/>{newline}'
        f'    <param name="optimization/settle_timeout" value="2.00" type="double"/>{newline}'
    )
    lines.insert(indexes[0] + 1, insertion)
    launch_after = "".join(lines)

    # All text and anchor checks happen before any backup or write.  A stale
    # source must leave the target tree untouched, including its backup set.
    bt_backup = backup(args.bt)
    launch_backup = backup(args.launch)
    before_bt = digest(args.bt)
    args.bt.write_text(bt_after, encoding="utf-8", newline="")
    args.launch.write_text(launch_after, encoding="utf-8", newline="")

    args.node_header.parent.mkdir(parents=True, exist_ok=True)
    args.node_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.header_payload, args.node_header)
    shutil.copy2(args.source_payload, args.node_source)
    files = [
        {"path": str(args.bt), "backup": str(bt_backup), "before_md5": before_bt, "after_md5": digest(args.bt)},
        {"path": str(args.launch), "backup": str(launch_backup), "before_md5": digest(launch_backup), "after_md5": digest(args.launch)},
    ]
    record = {
        "candidate": 2,
        "files": files,
        "added_files": [
            {"path": str(args.node_header), "md5": digest(args.node_header)},
            {"path": str(args.node_source), "md5": digest(args.node_source)},
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
