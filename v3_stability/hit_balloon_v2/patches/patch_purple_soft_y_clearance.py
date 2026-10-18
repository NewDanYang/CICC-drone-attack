#!/usr/bin/env python3
"""Add a purple-only inward position hold before reaching the y safety wall.

Usage: python3 patch_purple_soft_y_clearance.py CATKIN_ROOT BACKUP_DIRECTORY
Compile mission_pkg and restart after applying.
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(value) for value in sys.argv[1:])
rel = Path("src/mission_pkg/src/nodes/action/visual_servo.cpp")
path = root / rel
expected = "a63b57fa127a23cd8bb8e647f078ff21"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"visual_servo.cpp MD5 {actual} differs from audited source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

anchor = """NodeStatus VisualServo::onRunning() {
    updateTargetData();
    
    // 计算时间步长
"""
replacement = """NodeStatus VisualServo::onRunning() {
    updateTargetData();

    // Purple approaches and sprints have crossed y=-3.0 both before and
    // after contact. Use an inner control clearance without changing the
    // configured SafetyRecovery boundary or the other colors' trajectories.
    if (target_color_ == "purple" &&
        fcu_odom_ptr->pose.pose.position.y < -2.65) {
        auto inward = fcu_odom_ptr->pose.pose.position;
        inward.y = -2.45;
        const double yaw = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
        publishPosition(inward, yaw);
        current_state_ = ALIGN;
        align_stable_frames_ = 0;
        search_anchor_active_ = false;
        ROS_WARN_THROTTLE(0.5, "[%s]: PURPLE_SOFT_Y_CLEARANCE y=%.3f -> -2.450",
                          name().c_str(), fcu_odom_ptr->pose.pose.position.y);
        return NodeStatus::RUNNING;
    }
    
    // 计算时间步长
"""
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("onRunning anchor absent or non-unique; no change")
patched = text.replace(anchor, replacement, 1).encode("utf-8")
backup.mkdir(parents=True)
shutil.copy2(path, backup / "visual_servo.cpp")
(backup / "before_md5.txt").write_text(f"{expected}  {path}\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    text.splitlines(True), patched.decode("utf-8").splitlines(True),
    fromfile=str(rel), tofile=str(rel) + ".patched")), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    f'cp -p "{backup / "visual_servo.cpp"}" "{path}"\n'
    f'touch "{path}"\n'
    "set +u\nsource /opt/ros/noetic/setup.bash\nset -u\n"
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
