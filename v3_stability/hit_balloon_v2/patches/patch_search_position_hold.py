#!/usr/bin/env python3
"""Hold a fixed world position while yaw-scanning for a missing balloon.

Usage: python3 patch_search_position_hold.py CATKIN_ROOT BACKUP_DIRECTORY
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
    "    std::string target_color_;\n    bool search_anchor_active_;\n"
    "    geometry_msgs::Point search_anchor_;\n    double search_base_yaw_;\n    ros::Time search_start_time_;\n")
patched[cpp] = replace_once(patched[cpp],
    '    target_color_ = getInput<std::string>("target_color").value();',
    '    target_color_ = getInput<std::string>("target_color").value();\n'
    '    search_anchor_active_ = false;')
patched[cpp] = replace_once(patched[cpp],
    '''        // 搜索模式：原地慢转
        publishVelocityWithYawRate(0, 0, 0, search_yaw_rate_);
        ROS_WARN_THROTTLE(1.0, "[%s]: Target lost. Searching (yaw_rate=%.2f)...", 
                          name().c_str(), search_yaw_rate_);
        return NodeStatus::RUNNING;
    }
    
    // 计算基本量''',
    '''        // Body-frame zero velocity drifted 2.5 m during a 50-second
        // purple search. Keep the current world position while scanning yaw.
        if (!search_anchor_active_) {
            search_anchor_ = fcu_odom_ptr->pose.pose.position;
            search_base_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
            search_start_time_ = now;
            search_anchor_active_ = true;
            ROS_INFO("[%s]: SEARCH_ANCHOR pos=(%.3f,%.3f,%.3f) yaw=%.3f",
                     name().c_str(), search_anchor_.x, search_anchor_.y,
                     search_anchor_.z, search_base_yaw_);
        }
        const double search_yaw = search_base_yaw_ +
            search_yaw_rate_ * (now - search_start_time_).toSec();
        publishPosition(search_anchor_, search_yaw);
        ROS_WARN_THROTTLE(1.0, "[%s]: Target lost. Position-held search yaw=%.3f anchor=(%.2f,%.2f,%.2f)",
                          name().c_str(), search_yaw, search_anchor_.x,
                          search_anchor_.y, search_anchor_.z);
        return NodeStatus::RUNNING;
    }
    search_anchor_active_ = false;
    
    // 计算基本量''')

backup.mkdir(parents=True)
for relative, raw in original.items():
    path = root / relative
    saved = backup / relative
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, saved)
    old_text = raw.decode("utf-8").replace("\r\n", "\n")
    (backup / (relative.name + ".diff")).write_text("".join(difflib.unified_diff(
        old_text.splitlines(True), patched[relative].splitlines(True),
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
