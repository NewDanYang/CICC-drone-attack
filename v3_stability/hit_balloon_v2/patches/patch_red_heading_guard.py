#!/usr/bin/env python3
"""Gate red-balloon sprint on observed safe approach heading.

Usage: python3 patch_red_heading_guard.py CATKIN_ROOT BACKUP_DIRECTORY
The script verifies all three source hashes and backs up byte-exact originals.
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
    Path("src/mission_pkg/src/nodes/action/visual_servo.cpp"): "b09abd4b545d89cef8135913b9dc06b3",
    Path("src/mission_pkg/include/nodes/action/visual_servo.h"): "84d7918b3d2859453ad10b28428942bc",
    Path("src/mission_pkg/src/bt_ros.cpp"): "8da042a25554563220c98555824b7d62",
}
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
original = {}
for relative, expected in files.items():
    raw = (root / relative).read_bytes()
    if hashlib.md5(raw).hexdigest() != expected:
        raise SystemExit(f"source MD5 mismatch: {relative}; no changes made")
    if b"\r\n" in raw and raw.count(b"\r\n") != raw.count(b"\n"):
        raise SystemExit(f"mixed line endings: {relative}; no changes made")
    original[relative] = raw

def replace_once(s, old, new):
    if s.count(old) != 1:
        raise SystemExit("source anchor absent or non-unique; no changes made")
    return s.replace(old, new, 1)

cpp = Path("src/mission_pkg/src/nodes/action/visual_servo.cpp")
header = Path("src/mission_pkg/include/nodes/action/visual_servo.h")
bt = Path("src/mission_pkg/src/bt_ros.cpp")
patched = {relative: raw.decode("utf-8").replace("\r\n", "\n") for relative, raw in original.items()}

patched[header] = replace_once(
    patched[header], "    double max_area_ratio_;\n", "    double max_area_ratio_;\n    std::string target_color_;\n")
patched[cpp] = replace_once(
    patched[cpp], '             InputPort<double>("search_yaw_rate", 0.3, "搜索模式旋转速度 (rad/s)") };',
    '             InputPort<double>("search_yaw_rate", 0.3, "搜索模式旋转速度 (rad/s)"),\n'
    '             InputPort<std::string>("target_color", "", "当前气球颜色") };')
patched[cpp] = replace_once(
    patched[cpp], '    search_yaw_rate_ = getInput<double>("search_yaw_rate").value();',
    '    search_yaw_rate_ = getInput<double>("search_yaw_rate").value();\n'
    '    target_color_ = getInput<std::string>("target_color").value();')
patched[cpp] = replace_once(
    patched[cpp], '''        if (max_area_ratio_ > approach_area_threshold_ && isCentered()) {
            sendHoverCommand();
            ROS_INFO("[%s]: Centered close target disappeared (max_ratio=%.3f). SUCCESS.",
                     name().c_str(), max_area_ratio_);
            return NodeStatus::SUCCESS;
        }
''', '')
patched[cpp] = replace_once(
    patched[cpp], '''            if (current_ratio >= approach_area_threshold_ && !isCentered()) {
                vx = 0.0;
            }
            
            publishVelocityWithYawRate(vx, 0, vz, yaw_rate);''',
    '''            if (current_ratio >= approach_area_threshold_ && !isCentered()) {
                vx = 0.0;
            }
            // Red successes entered the sprint near yaw +/-pi; an observed
            // yaw=2.251 sprint ran toward the boundary and removed blue.
            bool red_heading_blocked = false;
            if (target_color_ == "red" && current_ratio >= approach_area_threshold_) {
                const double yaw = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
                const double yaw_error = std::abs(std::atan2(std::sin(yaw - M_PI), std::cos(yaw - M_PI)));
                red_heading_blocked = yaw_error > 0.45;
                if (red_heading_blocked) {
                    vx = 0.0;
                    ROS_WARN_THROTTLE(0.5, "[%s]: Red sprint heading blocked: yaw=%.3f error=%.3f rad",
                                      name().c_str(), yaw, yaw_error);
                }
            }
            
            publishVelocityWithYawRate(vx, 0, vz, yaw_rate);''')
patched[cpp] = replace_once(
    patched[cpp], 'if (current_ratio >= approach_area_threshold_ && isCentered()) {\n                current_state_ = SPRINTING;',
    'if (current_ratio >= approach_area_threshold_ && isCentered() && !red_heading_blocked) {\n                current_state_ = SPRINTING;')
patched[bt] = replace_once(
    patched[bt], '            "            <VisualServo pixel_target=\\"{balloon_pixel}\\" "',
    '            "            <VisualServo pixel_target=\\"{balloon_pixel}\\" target_color=\\"" + color + "\\" "')

backup.mkdir(parents=True)
for relative, raw in original.items():
    path = root / relative
    saved = backup / relative
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, saved)
    before_text = raw.decode("utf-8").replace("\r\n", "\n")
    (backup / (relative.name + ".diff")).write_text("".join(difflib.unified_diff(
        before_text.splitlines(True), patched[relative].splitlines(True),
        fromfile=str(relative), tofile=str(relative) + ".patched")), encoding="utf-8")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    final = patched[relative].replace("\n", newline).encode("utf-8")
    path.write_bytes(final)
    print(f"{relative} {hashlib.md5(raw).hexdigest()} -> {hashlib.md5(final).hexdigest()}")
(backup / "restore.sh").write_text(
    '#!/usr/bin/env bash\nset -euo pipefail\n'
    + "".join(f'cp -p "{backup / rel}" "{root / rel}"\n' for rel in files)
    + 'source /opt/ros/noetic/setup.bash\n'
    + f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
print("backup=" + str(backup))
