#!/usr/bin/env python3
"""Move only zone B's entry position away from the observed first collision.

Usage: python3 patch_purple_entry_route.py CATKIN_ROOT BACKUP_DIRECTORY
The live launch bytes are checked before writing. Restart the simulation so
roslaunch reloads the new parameters. No C++ source changes.
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
expected = "cff7ff38bf7ac9ef98ee890a1c8644e8"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"launch MD5 {actual} differs from audited 1.4 source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")


def once(raw, old, new):
    if raw.count(old) != 1:
        raise SystemExit(f"anchor {old!r} absent or non-unique; no change")
    return raw.replace(old, new, 1)


patched = original
for field in ("approach_pos", "goal"):
    space = " " if field == "approach_pos" else " " * 9
    old = f'name="balloon_zone_B/{field}"{space}value="5.3;-2.0;0.7"'.encode()
    new = f'name="balloon_zone_B/{field}"{space}value="3.5;-2.4;0.7"'.encode()
    patched = once(patched, old, new)

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
