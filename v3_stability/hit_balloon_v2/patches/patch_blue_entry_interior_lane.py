#!/usr/bin/env python3
"""Move only the C (blue) entry and goal 1 m inward from the x boundary.

Usage: python3 patch_blue_entry_interior_lane.py CATKIN_ROOT BACKUP_DIRECTORY
Requires the audited A-v4/B-v3 launch file. Restart sim after applying.
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(value) for value in sys.argv[1:])
rel = Path("src/mission_pkg/launch/llm_mission.launch")
path = root / rel
expected = "5550c580a4822e773a331bcef11f0c47"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"launch MD5 {actual} differs from audited A-v4/B-v3; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

patched = original
for field in ("approach_pos", "goal"):
    spacing = " " if field == "approach_pos" else " " * 9
    old = f'name="balloon_zone_C/{field}"{spacing}value="5.3;1.0;0.7"'.encode()
    new = f'name="balloon_zone_C/{field}"{spacing}value="4.3;1.0;0.7"'.encode()
    if patched.count(old) != 1:
        raise SystemExit(f"anchor {old!r} absent or non-unique; no change")
    patched = patched.replace(old, new, 1)
ET.fromstring(patched)

backup.mkdir(parents=True)
shutil.copy2(path, backup / "llm_mission.launch")
(backup / "before_md5.txt").write_text(f"{expected}  {path}\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    original.decode("utf-8").splitlines(True),
    patched.decode("utf-8").splitlines(True),
    fromfile=str(rel), tofile=str(rel) + ".patched")), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    f'cp -p "{backup / "llm_mission.launch"}" "{path}"\n'
    f'touch "{path}"\n'
    "echo 'Restart the simulation environment to reload the restored launch parameters.'\n",
    encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
