#!/usr/bin/env python3
"""Reduce only blue VisualServo sprint speed from 1.5 to 1.0 m/s.

Usage: python3 patch_blue_sprint_speed.py CATKIN_ROOT BACKUP_DIRECTORY
The blue-only default may be overridden by visual_servo/blue_sprint_velocity.
Compile mission_pkg and restart after applying.
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(arg) for arg in sys.argv[1:])
relative = Path("src/mission_pkg/src/bt_ros.cpp")
path = root / relative
expected = "488e0fa3894feb527a8b1e921770e9c4"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"bt_ros.cpp MD5 {actual} differs from audited source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

anchor = '        std::string vs_sprint_v = std::to_string(getDbl("visual_servo/sprint_velocity", 1.5));'
replacement = ('        std::string vs_sprint_v = std::to_string(color == "blue" ?\n'
               '            getDbl("visual_servo/blue_sprint_velocity", 1.0) :\n'
               '            getDbl("visual_servo/sprint_velocity", 1.5));')
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("sprint-speed anchor absent or non-unique; no change")
patched = text.replace(anchor, replacement, 1).encode("utf-8")
backup.mkdir(parents=True)
shutil.copy2(path, backup / "bt_ros.cpp")
(backup / "before_md5.txt").write_text(f"{expected}  {path}\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    text.splitlines(True), patched.decode("utf-8").splitlines(True),
    fromfile=str(relative), tofile=str(relative) + ".patched")), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    f'cp -p "{backup / "bt_ros.cpp"}" "{path}"\n'
    f'touch "{path}"\n'
    "source /opt/ros/noetic/setup.bash\n"
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
