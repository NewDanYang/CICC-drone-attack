#!/usr/bin/env python3
"""Hold purple target-loss search at least 0.55 m inside the y boundary.

Usage: python3 patch_purple_search_anchor_interior.py CATKIN_ROOT BACKUP_DIRECTORY
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

anchor = """            search_anchor_ = fcu_odom_ptr->pose.pose.position;
            search_base_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
"""
replacement = """            search_anchor_ = fcu_odom_ptr->pose.pose.position;
            // A purple search anchored at y=-2.92 repeatedly re-entered the
            // y=-3.0 boundary after SafetyRecovery moved the drone inward.
            if (target_color_ == "purple" && search_anchor_.y < -2.45) {
                ROS_WARN("[%s]: PURPLE_SEARCH_ANCHOR_INWARD y=%.3f -> -2.450",
                         name().c_str(), search_anchor_.y);
                search_anchor_.y = -2.45;
            }
            search_base_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
"""
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("search anchor assignment absent or non-unique; no change")
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
