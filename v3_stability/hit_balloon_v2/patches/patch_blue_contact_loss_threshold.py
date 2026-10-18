#!/usr/bin/env python3
"""Require stronger blue proximity evidence before contact-loss completion.

Usage: python3 patch_blue_contact_loss_threshold.py CATKIN_ROOT BACKUP_DIRECTORY
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
expected = "5a9bb56d2fef2aa3127c3a61bb153656"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"visual_servo.cpp MD5 {actual} differs from audited source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

anchor = "            max_area_ratio_ >= 0.75 * approach_area_threshold_ &&"
replacement = "            max_area_ratio_ >= 0.30 &&"
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("blue contact-loss anchor absent or non-unique; no change")
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
    "source /opt/ros/noetic/setup.bash\n"
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
