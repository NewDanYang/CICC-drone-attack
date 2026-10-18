#!/usr/bin/env python3
"""Limit only the landing return GoTo position setpoint to 0.6 m ahead.

Usage: python3 patch_return_goto_lookahead.py CATKIN_ROOT BACKUP_DIRECTORY
Compile mission_pkg and restart after applying. The restore script recompiles.
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys


if len(sys.argv) != 3:
    raise SystemExit(__doc__)

root, backup = (Path(arg) for arg in sys.argv[1:])
files = {
    "goto.cpp": (
        Path("src/mission_pkg/src/nodes/action/goto.cpp"),
        "f0710df499635efdc01dc8bd071ff018",
    ),
    "goto.h": (
        Path("src/mission_pkg/include/nodes/action/goto.h"),
        "835ee5c7cf6ea67de6f12e656285597b",
    ),
    "bt_ros.cpp": (
        Path("src/mission_pkg/src/bt_ros.cpp"),
        "0ce0f6ec147d516d20e1a89d612792a6",
    ),
}

if backup.exists():
    raise SystemExit("backup already exists; no change")
original = {}
for name, (relative, expected) in files.items():
    data = (root / relative).read_bytes()
    actual = hashlib.md5(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"{name} MD5 {actual} differs from audited source; no change")
    original[name] = data


def replace_once(data, old, new, name):
    text = data.decode("utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{name}: anchor absent or non-unique; no change")
    return text.replace(old, new, 1).encode("utf-8")


patched = dict(original)
patched["goto.h"] = replace_once(
    patched["goto.h"],
    "    double yaw_rate_limit;",
    "    double yaw_rate_limit;\n    double setpoint_lookahead_;",
    "goto.h",
)
patched["goto.cpp"] = replace_once(
    patched["goto.cpp"],
    '             InputPort<double>("yaw_rate", 0.5, "最大偏航角速度 (rad/s)") };',
    '             InputPort<double>("yaw_rate", 0.5, "最大偏航角速度 (rad/s)"),\n'
    '             InputPort<double>("setpoint_lookahead", 0.0, "最大位置设定点前视距离 (m); 0=禁用") };',
    "goto.cpp ports",
)
patched["goto.cpp"] = replace_once(
    patched["goto.cpp"],
    "    yaw_rate_limit = yaw_rate_res.value();",
    "    yaw_rate_limit = yaw_rate_res.value();\n"
    "    setpoint_lookahead_ = getInput<double>(\"setpoint_lookahead\").value();\n"
    "    if (setpoint_lookahead_ < 0.0) {\n"
    "        ROS_ERROR(\"[%s]: negative setpoint_lookahead\", name().c_str());\n"
    "        return NodeStatus::FAILURE;\n"
    "    }",
    "goto.cpp init",
)
patched["goto.cpp"] = replace_once(
    patched["goto.cpp"],
    "    publishPosition(target_pos, current_yaw_sp);",
    "    // The long return flight can overshoot x_min when PX4 sees a setpoint\n"
    "    // several metres away. Keep the commanded point near the measured pose.\n"
    "    geometry_msgs::Point commanded_pos = target_pos;\n"
    "    if (setpoint_lookahead_ > 0.0) {\n"
    "        const geometry_msgs::Point& current_pos = fcu_odom_ptr->pose.pose.position;\n"
    "        const double dx = target_pos.x - current_pos.x;\n"
    "        const double dy = target_pos.y - current_pos.y;\n"
    "        const double dz = target_pos.z - current_pos.z;\n"
    "        const double distance = std::sqrt(dx * dx + dy * dy + dz * dz);\n"
    "        if (distance > setpoint_lookahead_) {\n"
    "            const double ratio = setpoint_lookahead_ / distance;\n"
    "            commanded_pos.x = current_pos.x + ratio * dx;\n"
    "            commanded_pos.y = current_pos.y + ratio * dy;\n"
    "            commanded_pos.z = current_pos.z + ratio * dz;\n"
    "        }\n"
    "    }\n"
    "    publishPosition(commanded_pos, current_yaw_sp);",
    "goto.cpp control",
)
patched["bt_ros.cpp"] = replace_once(
    patched["bt_ros.cpp"],
    '"      <GoTo goal=\\\"" + ret_pos + "\\\" yaw=\\\"" + std::to_string(ret_yaw) + "\\\"/>\\n"',
    '"      <GoTo goal=\\\"" + ret_pos + "\\\" yaw=\\\"" + std::to_string(ret_yaw) + "\\\" setpoint_lookahead=\\\"0.6\\\"/>\\n"',
    "bt_ros.cpp landing return",
)

backup.mkdir(parents=True)
diffs = []
for name, (relative, expected) in files.items():
    source = root / relative
    shutil.copy2(source, backup / name)
    diffs.extend(difflib.unified_diff(
        original[name].decode("utf-8").splitlines(True),
        patched[name].decode("utf-8").splitlines(True),
        fromfile=str(relative), tofile=str(relative) + ".patched",
    ))
(backup / "changes.diff").write_text("".join(diffs), encoding="utf-8")
(backup / "before_md5.txt").write_text(
    "".join(f"{expected}  {root / relative}\n" for relative, expected in files.values()),
    encoding="ascii",
)
restore = ["#!/usr/bin/env bash", "set -euo pipefail"]
for name, (relative, _) in files.items():
    source = root / relative
    restore.extend([f'cp -p "{backup / name}" "{source}"', f'touch "{source}"'])
restore.extend(["source /opt/ros/noetic/setup.bash", f'cd "{root}"', "catkin_make --pkg mission_pkg -j2", ""])
(backup / "restore.sh").write_text("\n".join(restore), encoding="utf-8")
for name, (relative, _) in files.items():
    (root / relative).write_bytes(patched[name])
    print(f"{name}_after_md5={hashlib.md5(patched[name]).hexdigest()}")
print(f"backup={backup}")
