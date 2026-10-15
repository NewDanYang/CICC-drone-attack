#!/usr/bin/env python3
"""Remove zone-A entry yaw and high approach z from the audited live files.

Usage: python3 patch_red_entry_perception.py CATKIN_ROOT BACKUP_DIRECTORY
Only bt_ros.cpp and llm_mission.launch change. Compile mission_pkg and restart
the environment after applying this patch.
"""
import difflib
import hashlib
from pathlib import Path
import shutil
import sys


if len(sys.argv) != 3:
    raise SystemExit(__doc__)
root, backup = (Path(a) for a in sys.argv[1:])
bt_rel = Path("src/mission_pkg/src/bt_ros.cpp")
launch_rel = Path("src/mission_pkg/launch/llm_mission.launch")
expected = {
    bt_rel: "989415357ddcc33777989026ce873eca",
    launch_rel: "3fdc18d0f61052da1e93456078370926",
}
if backup.exists():
    raise SystemExit("backup directory already exists; no changes made")
original = {rel: (root / rel).read_bytes() for rel in expected}
for rel, raw in original.items():
    digest = hashlib.md5(raw).hexdigest()
    if digest != expected[rel]:
        raise SystemExit(f"{rel}: source MD5 {digest} differs from audited build; no changes made")


def once(data, old, new, label):
    if data.count(old) != 1:
        raise SystemExit(f"{label}: anchor absent or non-unique; no changes made")
    return data.replace(old, new, 1)


bt_raw = original[bt_rel]
if b"\r\n" in bt_raw and bt_raw.count(b"\r\n") != bt_raw.count(b"\n"):
    raise SystemExit("mixed bt_ros.cpp line endings; no changes made")
bt_newline = b"\r\n" if b"\r\n" in bt_raw else b"\n"
bt_text = bt_raw.decode("utf-8").replace("\r\n", "\n")
bt_text = once(
    bt_text,
    '''        double yaw_val = getDbl(param_prefix + "/yaw", -1.570796);
        std::string yaw = std::to_string(yaw_val);
        std::string balloon_name = color + "_balloon";''',
    '''        // Zone A preserves arrival heading. VisualServo scans and aligns
        // from the arrival pose; B/C keep their audited entry yaw commands.
        std::string yaw = zone == "A" ? "visual_servo" :
            std::to_string(getDbl(param_prefix + "/yaw", -1.570796));
        std::string entry_goto = zone == "A" ?
            "      <GoTo goal=\\\"" + goto_pos + "\\\"/>\\n" :
            "      <GoTo goal=\\\"" + goto_pos + "\\\" yaw=\\\"" + yaw + "\\\"/>\\n";
        std::string balloon_name = color + "_balloon";''',
    "zone-A entry yaw",
)
bt_text = once(
    bt_text,
    '''            "      <!-- 转向朝向" + zone + "区气球(" + color + ") -->\\n"
            "      <GoTo goal=\\\"" + goto_pos + "\\\" yaw=\\\"" + yaw + "\\\"/>\\n"
            "      <!-- 跟踪并撞击气球 -->\\n"''',
    '''            "      <!-- 进入" + zone + "区气球(" + color + ")观察位置 -->\\n"
            + entry_goto +
            "      <!-- 跟踪并撞击气球 -->\\n"''',
    "entry GoTo XML",
)
bt_patched = bt_text.replace("\n", bt_newline.decode()).encode("utf-8")

# Launch is modified as bytes: the live file has unusual CRLF bytes that
# must survive untouched outside these exact ASCII anchors.
launch_raw = original[launch_rel]
launch_patched = once(
    launch_raw,
    b'name="balloon_zone_A/approach_pos" value="5.3;1.0;1.5"',
    b'name="balloon_zone_A/approach_pos" value="5.3;1.0;0.7"',
    "red approach z",
)
lines = launch_patched.split(b"\n")
matching = [i for i, line in enumerate(lines) if b'balloon_zone_A/yaw' in line]
if len(matching) != 1 or b'<param name="balloon_zone_A/yaw"' not in lines[matching[0]]:
    raise SystemExit("zone-A yaw line absent or non-unique; no changes made")
del lines[matching[0]]
launch_patched = b"\n".join(lines)
if b'balloon_zone_A/yaw' in launch_patched:
    raise SystemExit("zone-A yaw remains in launch; no changes made")

backup.mkdir(parents=True)
for rel, raw in original.items():
    saved = backup / rel
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / rel, saved)
(backup / "before_md5.txt").write_text("".join(
    f"{expected[rel]}  {root / rel}\n" for rel in expected), encoding="ascii")
diff_parts = []
for rel, after in ((bt_rel, bt_patched), (launch_rel, launch_patched)):
    before_lines = original[rel].decode("utf-8", "replace").splitlines(True)
    after_lines = after.decode("utf-8", "replace").splitlines(True)
    diff_parts.extend(difflib.unified_diff(
        before_lines, after_lines, fromfile=str(rel), tofile=str(rel) + ".patched"))
(backup / "changes.diff").write_text("".join(diff_parts), encoding="utf-8")
(backup / "restore.sh").write_text(
    "#!/usr/bin/env bash\nset -euo pipefail\n" +
    "".join(f'cp -p "{backup / rel}" "{root / rel}"\n' for rel in expected) +
    f'touch "{root / bt_rel}"\n' +
    "source /opt/ros/noetic/setup.bash\n" +
    f'cd "{root}"\ncatkin_make --pkg mission_pkg -j2\n', encoding="utf-8")
(root / bt_rel).write_bytes(bt_patched)
(root / launch_rel).write_bytes(launch_patched)
print("before=" + repr({str(k): v for k, v in expected.items()}))
print("after=" + repr({str(bt_rel): hashlib.md5(bt_patched).hexdigest(),
                       str(launch_rel): hashlib.md5(launch_patched).hexdigest()}))
print("backup=" + str(backup))
