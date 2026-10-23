#!/usr/bin/env python3
"""Finish blue tracking after a near target disappears instead of searching 50 s.

Usage: python3 patch_blue_contact_loss_exit.py CATKIN_ROOT BACKUP_DIRECTORY
Requires the audited pre-1.3 visual_servo.cpp. Compile mission_pkg and restart.
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
expected = "e440050ecfc06657d5ac4b472411fef6"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"visual_servo.cpp MD5 {actual} differs from audited source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

anchor = """    if (current_state_ != SPRINTING && isTargetLost()) {
        if (current_state_ != ALIGN) {"""
replacement = """    if (current_state_ != SPRINTING && isTargetLost()) {
        // A blue balloon can pop while ALIGN is still active. The old 50 s
        // position-held search stays in the nearby red balloon's travel lane.
        // Finish only when the last blue detection was near and then vanished.
        const double last_ratio = last_target_.area() /
            (static_cast<double>(img_w_) * img_h_);
        const double lost_seconds = (now - last_valid_detection_time_).toSec();
        if (target_color_ == "blue" && has_ever_received_data_) {
            ROS_INFO_THROTTLE(1.0, "[%s]: BLUE_LOSS_SAMPLE area=%.4f max_area=%.4f lost_s=%.3f",
                              name().c_str(), last_ratio, max_area_ratio_, lost_seconds);
        }
        if (target_color_ == "blue" && has_ever_received_data_ &&
            max_area_ratio_ >= 0.75 * approach_area_threshold_ &&
            last_ratio >= 0.50 * approach_area_threshold_ &&
            lost_seconds <= data_timeout_ + 0.25) {
            sendHoverCommand();
            ROS_INFO("[%s]: BLUE_NEAR_CONTACT_LOSS_COMPLETE area=%.4f max_area=%.4f lost_s=%.3f",
                     name().c_str(), last_ratio, max_area_ratio_, lost_seconds);
            return NodeStatus::SUCCESS;
        }
        if (current_state_ != ALIGN) {"""
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("lost-target anchor absent or non-unique; no change")
patched = text.replace(anchor, replacement, 1).encode("utf-8")
backup.mkdir(parents=True)
shutil.copy2(path, backup / "visual_servo.cpp")
(backup / "before_md5.txt").write_text(f"{expected}  {path}\n", encoding="ascii")
diff = difflib.unified_diff(original.decode("utf-8").splitlines(True),
                            patched.decode("utf-8").splitlines(True),
                            fromfile=str(rel), tofile=str(rel) + ".patched")
(backup / "changes.diff").write_text("".join(diff), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n" +
    f'cp -p "{backup / "visual_servo.cpp"}" "{path}"\n' +
    f'touch "{path}"\n' +
    "source /opt/ros/noetic/setup.bash\n" +
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n',
    encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
