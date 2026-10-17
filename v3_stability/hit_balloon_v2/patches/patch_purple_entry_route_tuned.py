#!/usr/bin/env python3
"""Tune only zone B entry after the 3.5 m position missed its target.

Usage: python3 patch_purple_entry_route_tuned.py CATKIN_ROOT BACKUP_DIRECTORY
"""

import difflib
import hashlib
from pathlib import Path
import shutil
import sys


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(value) for value in sys.argv[1:])
rel = Path("src/mission_pkg/launch/llm_mission.launch")
path = root / rel
expected = "7b730887e836ba2861e00681a3a0f17b"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"launch MD5 {actual} differs from audited B-route v1; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")
patched = original
for field in ("approach_pos", "goal"):
    space = " " if field == "approach_pos" else " " * 9
    old = f'name="balloon_zone_B/{field}"{space}value="3.5;-2.4;0.7"'.encode()
    new = f'name="balloon_zone_B/{field}"{space}value="4.3;-2.4;0.7"'.encode()
    if patched.count(old) != 1:
        raise SystemExit(f"anchor {old!r} absent or non-unique; no change")
    patched = patched.replace(old, new, 1)
backup.mkdir(parents=True)
shutil.copy2(path, backup / "llm_mission.launch")
(backup / "before_md5.txt").write_text(f"{expected}  {path}\n", encoding="ascii")
diff = difflib.unified_diff(original.decode("utf-8", "replace").splitlines(True),
                            patched.decode("utf-8", "replace").splitlines(True),
                            fromfile=str(rel), tofile=str(rel) + ".patched")
(backup / "changes.diff").write_text("".join(diff), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n" +
    f'cp -p "{backup / "llm_mission.launch"}" "{path}"\n' +
    f'touch "{path}"\n' +
    "echo 'Restart the simulation environment to reload the restored launch parameters.'\n",
    encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
