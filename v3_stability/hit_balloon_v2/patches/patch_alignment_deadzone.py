#!/usr/bin/env python3
"""Make alignment acceptance reachable within the VisualServo control deadzones.

Usage: python3 patch_alignment_deadzone.py CATKIN_ROOT BACKUP_DIRECTORY
Refuses any source shape other than the audited observability build.
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
if before_md5 != "0422136d865fd7a738a2fc434f45bffd":
    raise SystemExit("source MD5 differs from audited observability build; no changes made")
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
if b"\r\n" in raw and raw.count(b"\r\n") != raw.count(b"\n"):
    raise SystemExit("mixed line endings; no changes made")
newline = b"\r\n" if b"\r\n" in raw else b"\n"
text = raw.decode("utf-8").replace("\r\n", "\n")
old = """    double tol_w = last_target_.width * center_tolerance_;
    double tol_h = last_target_.height * center_tolerance_;
    return std::abs(err_x) < tol_w && std::abs(err_y) < tol_h;"""
new = """    // A controller cannot reduce error inside its own zero-command deadzone.
    // Accept that region as centered even when the target box is very small.
    double tol_w = std::max(last_target_.width * center_tolerance_, deadzone_yaw_);
    double tol_h = std::max(last_target_.height * center_tolerance_, deadzone_vz_);
    return std::abs(err_x) <= tol_w && std::abs(err_y) <= tol_h;"""
if text.count(old) != 1:
    raise SystemExit("expected source anchor absent or non-unique; no changes made")
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
    f'source /opt/ros/noetic/setup.bash\ncd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print("source_md5_before=" + before_md5)
print("source_md5_after=" + hashlib.md5(patched).hexdigest())
print("backup=" + str(backup))
