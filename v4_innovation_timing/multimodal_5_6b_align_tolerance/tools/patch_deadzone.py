#!/usr/bin/env python3
"""Patch only the two VisualServo deadzone defaults and save a rollback copy."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


EXPECTED_SOURCE = "a63b57fa127a23cd8bb8e647f078ff21"
EXPECTED_HEADER = "d3324b0458b2160102f9bbf44546d035"


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"20", "30"}:
        raise SystemExit("usage: patch_deadzone.py 20|30 BACKUP_DIR")
    value = sys.argv[1]
    backup = Path(sys.argv[2])
    source = Path("/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp")
    header = Path("/home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/action/visual_servo.h")
    plugin = Path("/home/ubuntu/catkin_ws/devel/lib/visual_servo.so")
    if backup.exists():
        raise SystemExit(f"backup already exists: {backup}")
    if md5(source) != EXPECTED_SOURCE:
        raise SystemExit(f"source md5 mismatch: {md5(source)}")
    if md5(header) != EXPECTED_HEADER:
        raise SystemExit(f"header md5 mismatch: {md5(header)}")
    backup.mkdir(parents=True)
    shutil.copy2(source, backup / "visual_servo.cpp")
    shutil.copy2(header, backup / "visual_servo.h")
    if plugin.exists():
        shutil.copy2(plugin, backup / "visual_servo.so.before")
    (backup / "md5_before.txt").write_text(
        f"{md5(source)}  {source}\n{md5(header)}  {header}\n"
        + (f"{md5(plugin)}  {plugin}\n" if plugin.exists() else ""),
        encoding="ascii",
    )
    text = source.read_bytes().decode("utf-8")
    text2 = text.replace(
        'InputPort<double>("deadzone_yaw", 8.0,',
        f'InputPort<double>("deadzone_yaw", {value}.0,',
        1,
    ).replace(
        'InputPort<double>("deadzone_vz", 10.0,',
        f'InputPort<double>("deadzone_vz", {value}.0,',
        1,
    )
    if text2 == text:
        raise SystemExit("deadzone anchors not found")
    source.write_bytes(text2.encode("utf-8"))
    (backup / "md5_after_patch.txt").write_text(
        f"{md5(source)}  {source}\n{md5(header)}  {header}\n",
        encoding="ascii",
    )
    print(f"value={value}")
    print(f"source_before={EXPECTED_SOURCE}")
    print(f"source_after={md5(source)}")
    print(f"header={md5(header)}")
    print(f"backup={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
