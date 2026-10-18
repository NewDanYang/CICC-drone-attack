#!/usr/bin/env python3
"""Insert one blue-only landing return waypoint away from the red balloon lane.

Usage: python3 patch_blue_return_via.py CATKIN_ROOT BACKUP_DIRECTORY
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
rel = Path("src/mission_pkg/src/bt_ros.cpp")
path = root / rel
expected = "6ba77aa30eb4c42588d064820bcf852d"
original = path.read_bytes()
actual = hashlib.md5(original).hexdigest()
if actual != expected:
    raise SystemExit(f"bt_ros.cpp MD5 {actual} differs from audited source; no change")
if backup.exists():
    raise SystemExit("backup already exists; no change")

anchor = """    for (const auto& cmd : commands) {
        std::string node_xml = commandToXmlNode(cmd);
        if (!node_xml.empty()) {
            xml += node_xml;
        }
    }
    xml += R\"(    </Sequence>"""
replacement = """    bool blue_balloon_command = false;
    for (const auto& cmd : commands) {
        if (cmd.rfind("hit_balloon:", 0) == 0) {
            blue_balloon_command = (cmd == "hit_balloon:blue");
        }
        if (cmd == "land" && blue_balloon_command) {
            const std::string via = "1.0;-1.0;0.5";
            xml += "      <!-- Blue return via an interior lane -->\\n"
                   "      <GoTo goal=\\\"" + via + "\\\" setpoint_lookahead=\\\"0.6\\\"/>\\n";
        }
        std::string node_xml = commandToXmlNode(cmd);
        if (!node_xml.empty()) {
            xml += node_xml;
        }
    }
    xml += R\"(    </Sequence>"""
text = original.decode("utf-8")
if text.count(anchor) != 1:
    raise SystemExit("BT generation anchor absent or non-unique; no change")
patched = text.replace(anchor, replacement, 1).encode("utf-8")
backup.mkdir(parents=True)
shutil.copy2(path, backup / "bt_ros.cpp")
(backup / "before_md5.txt").write_text(f"{expected}  {path}\n", encoding="ascii")
(backup / "changes.diff").write_text("".join(difflib.unified_diff(
    text.splitlines(True), patched.decode("utf-8").splitlines(True),
    fromfile=str(rel), tofile=str(rel) + ".patched")), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    f'cp -p "{backup / "bt_ros.cpp"}" "{path}"\n'
    f'touch "{path}"\n'
    "set +u\nsource /opt/ros/noetic/setup.bash\nset -u\n"
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
path.write_bytes(patched)
print(f"before_md5={expected}")
print(f"after_md5={hashlib.md5(patched).hexdigest()}")
print(f"backup={backup}")
