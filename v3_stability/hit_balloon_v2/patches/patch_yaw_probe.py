#!/usr/bin/env python3
"""Add an opt-in +/-0.2 rad/s visual yaw polarity probe.

Usage: python3 patch_yaw_probe.py CATKIN_ROOT BACKUP_DIRECTORY
Set /visual_servo/yaw_probe=true for one formal flight, then restore.
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
    Path("src/mission_pkg/src/nodes/action/visual_servo.cpp"): "418ae9129a266bc4ac3c013f4232011b",
    Path("src/mission_pkg/include/nodes/action/visual_servo.h"): "1093026e507c382d075fe00cfbef64b4",
}
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
original = {}
for relative, md5 in files.items():
    raw = (root / relative).read_bytes()
    if hashlib.md5(raw).hexdigest() != md5:
        raise SystemExit(f"source MD5 mismatch: {relative}; no changes made")
    original[relative] = raw

def replace_once(s, old, new):
    if s.count(old) != 1:
        raise SystemExit("source anchor absent or non-unique; no changes made")
    return s.replace(old, new, 1)

cpp = Path("src/mission_pkg/src/nodes/action/visual_servo.cpp")
header = Path("src/mission_pkg/include/nodes/action/visual_servo.h")
patched = {relative: raw.decode("utf-8").replace("\r\n", "\n") for relative, raw in original.items()}
patched[header] = replace_once(patched[header],
    "    std::string target_color_;\n",
    "    std::string target_color_;\n    bool yaw_probe_enabled_;\n    bool yaw_probe_started_;\n    bool yaw_probe_done_;\n    double yaw_probe_first_rate_;\n    ros::Time yaw_probe_start_time_;\n")
patched[cpp] = replace_once(patched[cpp],
    '    target_color_ = getInput<std::string>("target_color").value();',
    '    target_color_ = getInput<std::string>("target_color").value();\n'
    '    ros::param::param("/visual_servo/yaw_probe", yaw_probe_enabled_, false);\n'
    '    yaw_probe_started_ = false;\n'
    '    yaw_probe_done_ = false;\n'
    '    yaw_probe_first_rate_ = 0.0;')
patched[cpp] = replace_once(patched[cpp],
    '''    // 目标丢失处理（冲刺阶段不检查）
    if (current_state_ != SPRINTING && isTargetLost()) {''',
    '''    // A one-flight opt-in measurement: hover while commanding two fixed
    // yaw rates for two seconds each, and log raw target center and odom yaw.
    if (yaw_probe_enabled_ && !yaw_probe_done_) {
        if (!yaw_probe_started_ && !isTargetLost()) {
            yaw_probe_started_ = true;
            yaw_probe_start_time_ = now;
            yaw_probe_first_rate_ = last_target_.center_x > img_cx_ ? -0.2 : 0.2;
            ROS_INFO("[%s]: YAW_PROBE_START color=%s first_rate=%.3f pixel_x=%.1f",
                     name().c_str(), target_color_.c_str(), yaw_probe_first_rate_, last_target_.center_x);
        }
        if (yaw_probe_started_) {
            const double elapsed = (now - yaw_probe_start_time_).toSec();
            if (elapsed < 4.0) {
                const double command = elapsed < 2.0 ? yaw_probe_first_rate_ : -yaw_probe_first_rate_;
                publishVelocityWithYawRate(0.0, 0.0, 0.0, command);
                ROS_INFO_THROTTLE(0.1, "[%s]: YAW_PROBE t=%.3f cmd=%.3f pixel_x=%.1f fresh=%d yaw=%.3f",
                                  name().c_str(), elapsed, command, last_target_.center_x,
                                  !isTargetLost(), PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation));
                return NodeStatus::RUNNING;
            }
            yaw_probe_done_ = true;
            ROS_INFO("[%s]: YAW_PROBE_END elapsed=%.3f pixel_x=%.1f fresh=%d",
                     name().c_str(), elapsed, last_target_.center_x, !isTargetLost());
        }
    }

    // 目标丢失处理（冲刺阶段不检查）
    if (current_state_ != SPRINTING && isTargetLost()) {''')

backup.mkdir(parents=True)
for relative, raw in original.items():
    path = root / relative
    saved = backup / relative
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, saved)
    original_text = raw.decode("utf-8").replace("\r\n", "\n")
    (backup / (relative.name + ".diff")).write_text("".join(difflib.unified_diff(
        original_text.splitlines(True), patched[relative].splitlines(True),
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
