#!/usr/bin/env python3
"""Retry blue alignment when a sprint ends with the target clearly still in view.

Usage: python3 patch_blue_visible_after_sprint.py CATKIN_ROOT BACKUP_DIRECTORY
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
expected = "ae8e6172e4ddbfc851bcfdf080dc2aec"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"visual_servo.cpp MD5 {actual} differs from audited source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

anchor = """                sendHoverCommand();
                ROS_INFO("[%s]: Sprint completed (%.1fs). SUCCESS.", name().c_str(), sprint_dt);
                return NodeStatus::SUCCESS;
"""
replacement = """                // A visible, far-off-center blue balloon is direct evidence
                // that the fixed-time sprint missed. Stop and realign rather
                // than reporting a hit and flying the landing return route.
                if (target_color_ == "blue" && !isTargetLost() &&
                    current_ratio >= 0.03 && std::abs(err_x) > 0.20 * img_w_) {
                    sendHoverCommand();
                    current_state_ = ALIGN;
                    align_stable_frames_ = 0;
                    ROS_WARN("[%s]: BLUE_SPRINT_VISIBLE_RETRY err_x=%.1f area=%.4f",
                             name().c_str(), err_x, current_ratio);
                    break;
                }
                sendHoverCommand();
                ROS_INFO("[%s]: Sprint completed (%.1fs). SUCCESS.", name().c_str(), sprint_dt);
                return NodeStatus::SUCCESS;
"""
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("sprint completion anchor absent or non-unique; no change")
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
