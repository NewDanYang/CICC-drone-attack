#!/usr/bin/env python3
"""Add near-target sprint abort to the audited 2026-10-15 VisualServo build.

Usage: python3 patch_sprint_abort_on_contact.py CATKIN_ROOT BACKUP_DIRECTORY
Only the SPRINTING branch changes. The caller must compile mission_pkg and
restart the simulator after this source patch.
"""
import difflib
import hashlib
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(a) for a in sys.argv[1:])
relative = Path("src/mission_pkg/src/nodes/action/visual_servo.cpp")
path = root / relative
raw = path.read_bytes()
before_md5 = hashlib.md5(raw).hexdigest()
if before_md5 != "e440050ecfc06657d5ac4b472411fef6":
    raise SystemExit(f"source MD5 {before_md5} differs from audited build; no changes made")
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
if b"\r\n" in raw and raw.count(b"\r\n") != raw.count(b"\n"):
    raise SystemExit("mixed line endings; no changes made")
newline = b"\r\n" if b"\r\n" in raw else b"\n"
text = raw.decode("utf-8").replace("\r\n", "\n")
old = '''            // 超时 → 完成
            if (sprint_dt >= sprint_time_) {'''
new = '''            // max_area_ratio_ is refreshed before this switch, so comparing
            // current_ratio to it cannot detect growth here. A 25% image area
            // is a near-contact cue in the real three-balloon frames. The
            // passed-target cue handles a balloon sliding off to one side.
            const double near_area = std::max(0.12, approach_area_threshold_ * 1.5);
            const bool area_close = sprint_dt >= 0.4 && sprint_dt < sprint_time_ &&
                                    !isTargetLost() && current_ratio >= 0.25;
            const bool passed_target = sprint_dt >= 0.8 && sprint_dt < sprint_time_ &&
                                       !isTargetLost() && current_ratio >= near_area &&
                                       std::abs(err_x) >= img_w_ * 0.35;
            const bool lost_close = sprint_dt < sprint_time_ && isTargetLost() &&
                                    max_area_ratio_ >= near_area;
            if (area_close || passed_target || lost_close) {
                const auto& pose = fcu_odom_ptr->pose.pose;
                const char* reason = area_close ? "area" : (passed_target ? "passed_target" : "lost");
                ROS_WARN("[%s]: SPRINT_ABORT_NEAR_TARGET reason=%s dt=%.3f area=%.4f max_area=%.4f err_x=%.1f near_area=%.4f pos=(%.3f,%.3f,%.3f)",
                         name().c_str(), reason, sprint_dt,
                         current_ratio, max_area_ratio_, err_x, near_area,
                         pose.position.x, pose.position.y, pose.position.z);
                sendHoverCommand();
                return NodeStatus::SUCCESS;
            }

            // 超时 → 完成
            if (sprint_dt >= sprint_time_) {'''
if text.count(old) != 1:
    raise SystemExit("expected SPRINTING block absent or non-unique; no changes made")
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
    f'touch "{path}"\n'
    'source /opt/ros/noetic/setup.bash\n'
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print("source_md5_before=" + before_md5)
print("source_md5_after=" + hashlib.md5(patched).hexdigest())
print("backup=" + str(backup))
