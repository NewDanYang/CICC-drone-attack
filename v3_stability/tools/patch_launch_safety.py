#!/usr/bin/env python3
"""Patch the safety margin params in llm_mission.launch, byte-safely.

Replaces the single `safety/recovery_margin` param with the decoupled
`recovery_target_margin` + `release_margin` pair that the rebuilt
mavros_cnt.cpp reads. Operates on bytes so the file's UTF-8 CJK comments
and CRLF line endings survive untouched.
"""
import sys

PATH = "/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch"

OLD = b'<param name="safety/recovery_margin" value="0.20" type="double"/>'
NEW = (b'<param name="safety/recovery_target_margin" value="0.30" type="double"/>\r\n'
       b'    <param name="safety/release_margin" value="0.15" type="double"/>')

data = open(PATH, "rb").read()

if b"recovery_target_margin" in data:
    print("ALREADY_PATCHED")
    sys.exit(0)

n = data.count(OLD)
if n != 1:
    print(f"UNEXPECTED_MATCH_COUNT={n}")
    sys.exit(1)

open(PATH, "wb").write(data.replace(OLD, NEW))
print("PATCHED")

# Re-validate with the same parser roslaunch uses.
import xml.dom.minidom as minidom
minidom.parse(PATH)
print("XML_OK")
