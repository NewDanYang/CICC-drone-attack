#!/usr/bin/env python3
"""Require a centered target before the area threshold can start a sprint.

Usage: python3 patch_sprint_center_gate.py CATKIN_ROOT BACKUP_DIRECTORY
Refuses any C++ source other than the audited alignment-deadzone build.
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
if before_md5 != "4d9a99091f3d1f68facb743d2fab14e2":
    raise SystemExit("source MD5 differs from audited deadzone build; no changes made")
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
if b"\r\n" in raw and raw.count(b"\r\n") != raw.count(b"\n"):
    raise SystemExit("mixed line endings; no changes made")
newline = b"\r\n" if b"\r\n" in raw else b"\n"
text = raw.decode("utf-8").replace("\r\n", "\n")
old = '''            // 面积达阈值 → 触发冲刺
            if (current_ratio >= approach_area_threshold_) {
                current_state_ = SPRINTING;
                sprint_start_time_ = ros::Time::now();
                const auto& sprint_pose = fcu_odom_ptr->pose.pose;
                ROS_INFO("[%s]: SPRINT_START pos=(%.3f,%.3f,%.3f) yaw=%.3f err=(%.1f,%.1f) area=%.4f velocity=%.3f time=%.3f",
                         name().c_str(), sprint_pose.position.x, sprint_pose.position.y,
                         sprint_pose.position.z, PoseUtils::getYawFromQuat(sprint_pose.orientation),
                         err_x, err_y, current_ratio, sprint_velocity_, sprint_time_);
                ROS_INFO("[%s]: Area %.1f%% >= %.1f%% -> SPRINT! (sprint_vel=%.2f, time=%.1fs)", 
                         name().c_str(), current_ratio*100, approach_area_threshold_*100,
                         sprint_velocity_, sprint_time_);
            }'''
new = old.replace(
    'if (current_ratio >= approach_area_threshold_) {',
    'if (current_ratio >= approach_area_threshold_ && isCentered()) {'
).replace(
    '            }',
    '''            } else if (current_ratio >= approach_area_threshold_) {
                ROS_WARN_THROTTLE(0.5, "[%s]: Sprint area ready but off-center err:(%.0f,%.0f); continue alignment",
                                  name().c_str(), err_x, err_y);
            }''',
    1,
)
if text.count(old) != 1:
    raise SystemExit("expected sprint block absent or non-unique; no changes made")
patched_text = text.replace(old, new, 1)
patched = patched_text.replace("\n", newline.decode()).encode("utf-8")
backup.mkdir(parents=True)
saved = backup / relative
saved.parent.mkdir(parents=True)
shutil.copy2(path, saved)
(backup / "before_md5.txt").write_text(before_md5 + "  " + str(path) + "\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    text.splitlines(True), patched_text.splitlines(True),
    fromfile=str(relative), tofile=str(relative) + ".patched")), encoding="utf-8")
(backup / "restore.sh").write_text(
    '#!/usr/bin/env bash\nset -euo pipefail\n'
    f'cp -p "{saved}" "{path}"\n'
    'source /opt/ros/noetic/setup.bash\n'
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print("source_md5_before=" + before_md5)
print("source_md5_after=" + hashlib.md5(patched).hexdigest())
print("backup=" + str(backup))
