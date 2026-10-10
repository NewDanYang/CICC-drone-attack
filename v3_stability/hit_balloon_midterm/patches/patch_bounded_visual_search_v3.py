from pathlib import Path
import hashlib, shutil, sys, difflib
root, backup = map(Path, sys.argv[1:3])
p=Path("src/mission_pkg/src/nodes/action/visual_servo.cpp")
raw=(root/p).read_bytes(); t=raw.decode("utf-8").replace("\r\n","\n")
if "search_timeout_v2" in t: raise RuntimeError("Cumulative search patch already present; no changes made")
u=t.find("void VisualServo::updateTargetData()")
z=t.find("bool VisualServo::isTargetLost()",u)
if u<0 or z<0: raise RuntimeError("updateTargetData range not found; no changes made")
region=t[u:z]; kept=[x for x in region.splitlines(True) if "search_start_time_ = ros::Time(0);" not in x]
if len(kept)==len(region.splitlines(True)): raise RuntimeError("No target-reset timer found; no changes made")
t=t[:u]+"".join(kept)+t[z:]
anchor="    search_timeout_ = getInput<double>(\"search_timeout\").value();"
if anchor not in t: raise RuntimeError("search_timeout parameter missing; v1 not deployed; no changes made")
t=t.replace(anchor,anchor+"\n    // search_timeout_v2: cumulative search; detections do not reset the timer",1)
backup.mkdir(parents=True,exist_ok=False); (backup/p).parent.mkdir(parents=True,exist_ok=True); shutil.copy2(root/p,backup/p)
before=raw.decode("utf-8").replace("\r\n","\n")
(backup/"changes.diff").write_text("".join(difflib.unified_diff(before.splitlines(True),t.splitlines(True),fromfile=str(p),tofile=str(p)+".patched")),encoding="utf-8")
(backup/"restore.sh").write_text("#!/usr/bin/env bash\nset -e\ncp -p \""+str(backup/p)+"\" \""+str(root/p)+"\"\ncd \""+str(root)+"\"\ncatkin_make --pkg mission_pkg -j2\n",encoding="utf-8")
(root/p).write_bytes(t.encode("utf-8"))
print("Patched cumulative search timeout"); print("Backup:",backup)

