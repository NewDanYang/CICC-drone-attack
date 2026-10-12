#!/usr/bin/env python3
"""Hold position while close but off-center; reacquire an off-center lost target.

Usage: python3 patch_close_align_reacquire.py CATKIN_ROOT BACKUP_DIRECTORY
Refuses any C++ source other than the audited sprint-center-gate build.
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
if before_md5 != "74802b9d2082aa408b97b555685aee2a":
    raise SystemExit("source MD5 differs from audited sprint gate; no changes made")
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
if b"\r\n" in raw and raw.count(b"\r\n") != raw.count(b"\n"):
    raise SystemExit("mixed line endings; no changes made")
newline = b"\r\n" if b"\r\n" in raw else b"\n"
text = raw.decode("utf-8").replace("\r\n", "\n")
changes = [
    ('''        if (max_area_ratio_ > approach_area_threshold_) {
            sendHoverCommand();
            ROS_INFO("[%s]: Target lost after approach (max_ratio=%.3f). SUCCESS.", 
                     name().c_str(), max_area_ratio_);
            return NodeStatus::SUCCESS;
        }
        // 搜索模式：原地慢转''',
     '''        if (max_area_ratio_ > approach_area_threshold_ && isCentered()) {
            sendHoverCommand();
            ROS_INFO("[%s]: Centered close target disappeared (max_ratio=%.3f). SUCCESS.",
                     name().c_str(), max_area_ratio_);
            return NodeStatus::SUCCESS;
        }
        if (current_state_ != ALIGN) {
            current_state_ = ALIGN;
            align_stable_frames_ = 0;
            ROS_WARN("[%s]: Off-center target lost after approach; return to ALIGN and search.",
                     name().c_str());
        }
        // 搜索模式：原地慢转'''),
    ('''            double vx = forward_velocity_ * align_ratio;
            
            publishVelocityWithYawRate(vx, 0, vz, yaw_rate);''',
     '''            double vx = forward_velocity_ * align_ratio;
            // Close range with an off-center target needs yaw/vz correction,
            // not more forward travel that drives the target out of frame.
            if (current_ratio >= approach_area_threshold_ && !isCentered()) {
                vx = 0.0;
            }
            
            publishVelocityWithYawRate(vx, 0, vz, yaw_rate);'''),
]
for old, _ in changes:
    if text.count(old) != 1:
        raise SystemExit("expected source anchor absent or non-unique; no changes made")
patched_text = text
for old, new in changes:
    patched_text = patched_text.replace(old, new, 1)
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
