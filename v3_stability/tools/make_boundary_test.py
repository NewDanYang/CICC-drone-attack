#!/usr/bin/env python3
"""Create a boundary-test copy of llm_mission.launch with a tightened y_max.

Purpose: force the SafetyRecovery path to actually fire during a real mission,
so we can observe whether it now COMPLETES (the whole point of the v1 fix).

Design constraint for the test value:
  - every normal waypoint must stay INSIDE the boundary, so the mission can
    still progress and its goals stay reachable. Balloon zone A sits at
    y = 1.0, which is the largest y of any waypoint.
  - the boundary must be low enough that the drift/overshoot which triggered
    the real failure (y drifted 1.0 -> 3.0) crosses it.
So y_max = 1.5: all goals (max y = 1.0) remain inside and reachable, while a
modest overshoot past the balloon goal now trips recovery.

With target_margin=0.30 / release_margin=0.15 this gives:
  recovery target y = 1.50 - 0.30 = 1.20
  release requires  y <= 1.50 - 0.15 = 1.35   -> 1.20 is inside, so it latches.
The old (buggy) code with a single 0.20 margin would target 1.30 and require
  y <= 1.30 to release -- target exactly ON the release boundary.
"""
import shutil
import xml.dom.minidom as minidom

SRC = "/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch"
DST = "/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission_boundarytest.launch"

shutil.copyfile(SRC, DST)

data = open(DST, "rb").read()
old = b'<param name="safety/y_max" value="3.0" type="double"/>'
new = b'<param name="safety/y_max" value="1.5" type="double"/>'

n = data.count(old)
if n != 1:
    raise SystemExit(f"UNEXPECTED y_max match count: {n}")
open(DST, "wb").write(data.replace(old, new))

minidom.parse(DST)
print("TEST_LAUNCH_OK", DST)
for line in open(DST, encoding="utf-8"):
    if "safety/" in line:
        print("   ", line.rstrip())
