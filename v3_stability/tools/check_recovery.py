#!/usr/bin/env python3
"""Extract the SafetyRecovery sequence from an llm_mission stdout log.

Answers the one question that matters for the v1 fix: did recovery ENTER and
then COMPLETE, or did it enter and stall (the old bug)?
"""
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/llm_boundarytest.out"

pat = re.compile(r"\[SafetyRecovery\]|ENTER DRONE OUT|recovery target|COMPLETE recovery|"
                 r"RELEASE confirmation|confirmation reset|Safety boundary enabled|"
                 r"target_margin|Invalid SafetyRecovery")
lines = [l.rstrip() for l in open(path, encoding="utf-8", errors="replace") if pat.search(l)]

print(f"--- {len(lines)} SafetyRecovery lines in {path} ---")
for l in lines:
    # strip ROS prefix noise down to the message
    m = re.search(r"(\[SafetyRecovery\].*)$", l)
    print("   ", (m.group(1) if m else l)[:150])

entered = any("ENTER DRONE OUT" in l for l in lines)
completed = any("COMPLETE recovery" in l for l in lines)
resets = sum(1 for l in lines if "confirmation reset" in l)

print()
print(f"entered   : {entered}")
print(f"completed : {completed}")
print(f"resets    : {resets}")
if entered and completed:
    print("VERDICT   : recovery ENTERED and COMPLETED  <-- fix works")
elif entered and not completed:
    print("VERDICT   : recovery ENTERED but did NOT complete  <-- still broken")
elif not entered:
    print("VERDICT   : recovery never triggered (test did not exercise the branch)")
