#!/usr/bin/env python3
"""Add sprint start/end telemetry without changing VisualServo control.

Usage: python3 patch_sprint_observability.py CATKIN_ROOT BACKUP_DIRECTORY
Refuses any source shape other than the audited 2026-10-12 baseline.
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(arg) for arg in sys.argv[1:])
relative = Path("src/mission_pkg/src/nodes/action/visual_servo.cpp")
path = root / relative
raw = path.read_bytes()
before_md5 = hashlib.md5(raw).hexdigest()
if before_md5 != "a97f5af29c2797e47a55bb3d7d216106":
    raise SystemExit("source MD5 differs from audited baseline; no changes made")
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
if b"\r\n" in raw and raw.count(b"\r\n") != raw.count(b"\n"):
    raise SystemExit("mixed line endings; no changes made")
newline = b"\r\n" if b"\r\n" in raw else b"\n"
text = raw.decode("utf-8").replace("\r\n", "\n")
if "SPRINT_START pos=" in text or "SPRINT_END pos=" in text:
    raise SystemExit("observability patch already present; no changes made")

old_include = '#include "nodes/action/visual_servo.h"\n'
new_include = old_include + '#include "utils/pose_utils.h"\n'
old_start = '''                ROS_INFO("[%s]: Area %.1f%% >= %.1f%% -> SPRINT! (sprint_vel=%.2f, time=%.1fs)", 
                         name().c_str(), current_ratio*100, approach_area_threshold_*100,
                         sprint_velocity_, sprint_time_);'''
new_start = '''                const auto& sprint_pose = fcu_odom_ptr->pose.pose;
                ROS_INFO("[%s]: SPRINT_START pos=(%.3f,%.3f,%.3f) yaw=%.3f err=(%.1f,%.1f) area=%.4f velocity=%.3f time=%.3f",
                         name().c_str(), sprint_pose.position.x, sprint_pose.position.y,
                         sprint_pose.position.z, PoseUtils::getYawFromQuat(sprint_pose.orientation),
                         err_x, err_y, current_ratio, sprint_velocity_, sprint_time_);
                ROS_INFO("[%s]: Area %.1f%% >= %.1f%% -> SPRINT! (sprint_vel=%.2f, time=%.1fs)", 
                         name().c_str(), current_ratio*100, approach_area_threshold_*100,
                         sprint_velocity_, sprint_time_);'''
old_end = '''                sendHoverCommand();
                ROS_INFO("[%s]: Sprint completed (%.1fs). SUCCESS.", name().c_str(), sprint_dt);
                return NodeStatus::SUCCESS;'''
new_end = '''                const auto& sprint_pose = fcu_odom_ptr->pose.pose;
                ROS_INFO("[%s]: SPRINT_END pos=(%.3f,%.3f,%.3f) yaw=%.3f err=(%.1f,%.1f) area=%.4f target_fresh=%d velocity=%.3f time=%.3f",
                         name().c_str(), sprint_pose.position.x, sprint_pose.position.y,
                         sprint_pose.position.z, PoseUtils::getYawFromQuat(sprint_pose.orientation),
                         err_x, err_y, current_ratio, !isTargetLost(), sprint_velocity_, sprint_time_);
                sendHoverCommand();
                ROS_INFO("[%s]: Sprint completed (%.1fs). SUCCESS.", name().c_str(), sprint_dt);
                return NodeStatus::SUCCESS;'''
for old, new in [(old_include, new_include), (old_start, new_start), (old_end, new_end)]:
    if text.count(old) != 1:
        raise SystemExit("expected source anchor absent or non-unique; no changes made")
    text = text.replace(old, new, 1)
patched = text.replace("\n", newline.decode()).encode("utf-8")
backup.mkdir(parents=True)
saved = backup / relative
saved.parent.mkdir(parents=True)
shutil.copy2(path, saved)
(backup / "before_md5.txt").write_text(before_md5 + "  " + str(path) + "\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    raw.decode("utf-8").replace("\r\n", "\n").splitlines(True),
    text.splitlines(True), fromfile=str(relative), tofile=str(relative) + ".patched")),
    encoding="utf-8")
(backup / "restore.sh").write_text(
    '#!/usr/bin/env bash\nset -euo pipefail\n'
    f'cp -p "{saved}" "{path}"\n'
    f'source /opt/ros/noetic/setup.bash\ncd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print("source_md5_before=" + before_md5)
print("source_md5_after=" + hashlib.md5(patched).hexdigest())
print("backup=" + str(backup))
