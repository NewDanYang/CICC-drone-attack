#!/usr/bin/env python3
"""Point red-zone entry toward the observed red rover path (negative x).

Usage: python3 patch_red_entry_yaw.py CATKIN_ROOT BACKUP_DIRECTORY
Byte-level launch edit: preserves UTF-8 comments and CRLF without parsing XML.
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(arg) for arg in sys.argv[1:])
relative = Path("src/mission_pkg/launch/llm_mission.launch")
path = root / relative
raw = path.read_bytes()
before_md5 = hashlib.md5(raw).hexdigest()
if before_md5 != "a1f0cfc65cd7357ab38c4a09ad4ef45a":
    raise SystemExit("launch MD5 differs from audited baseline; no changes made")
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
old = b'<param name="balloon_zone_A/yaw"          value="1.5708"        type="double"/>'
new = b'<param name="balloon_zone_A/yaw"          value="3.14159"       type="double"/>'
if raw.count(old) != 1:
    raise SystemExit("expected launch anchor absent or non-unique; no changes made")
patched = raw.replace(old, new, 1)
backup.mkdir(parents=True)
saved = backup / relative
saved.parent.mkdir(parents=True)
shutil.copy2(path, saved)
(backup / "before_md5.txt").write_text(before_md5 + "  " + str(path) + "\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    raw.decode("utf-8").replace("\r\n", "\n").splitlines(True),
    patched.decode("utf-8").replace("\r\n", "\n").splitlines(True),
    fromfile=str(relative), tofile=str(relative) + ".patched")), encoding="utf-8")
(backup / "restore.sh").write_text(
    '#!/usr/bin/env bash\nset -euo pipefail\n'
    f'cp -p "{saved}" "{path}"\n'
    'echo "launch restored; restart /llm_mission_node before the next trial"\n',
    encoding="utf-8")
path.write_bytes(patched)
print("launch_md5_before=" + before_md5)
print("launch_md5_after=" + hashlib.md5(patched).hexdigest())
print("backup=" + str(backup))
