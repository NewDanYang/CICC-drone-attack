#!/usr/bin/env bash
# Launch detached: this resets only the already-owned, disarmed simulator.
set -euo pipefail
condition="${1:?candidate|baseline}"
backup="${2:?backup directory}"
reset_mode="${3:-reset}"
case "$reset_mode" in reset|no-reset) ;; *) exit 2;; esac
test ! -e /tmp/tcei_formal_trial.lock
set +u
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
grep -q 'armed: False' <<< "$state"
nodes="$(rosnode list)"
if grep -Fxq /llm_mission_node <<< "$nodes"; then rosnode kill /llm_mission_node; fi
while read -r node; do
  test -z "$node" || rosnode kill "$node" || true
done < <(grep -E '^/mission_once(_|$)' <<< "$nodes" || true)
sleep 3
# The sealed interactive entry can remain blocked in input() after rosnode kill.
# Stop only exact Python argv entries, after the disarmed/no-trial checks above.
/usr/bin/python3 - <<'PY'
import os,re,signal,time
from pathlib import Path
def missions():
    found={}
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():continue
        try:argv=(process/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
        if (argv and re.fullmatch(rb'python(?:[0-9.]*)?',argv[0].rsplit(b'/',1)[-1])
                and any(arg.rsplit(b'/',1)[-1]==b'mission_once.py' for arg in argv[1:])):
            found[int(process.name)]=argv
    return found
owned=missions()
print('STOP_IDLE_MODEL_PIDS',sorted(owned),flush=True)
for pid in owned:
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:pass
deadline=time.monotonic()+20
while missions() and time.monotonic()<deadline:time.sleep(.2)
for pid,argv in missions().items():
    if owned.get(pid)!=argv:raise RuntimeError('Unexpected new mission process')
    try:os.kill(pid,signal.SIGKILL)
    except ProcessLookupError:pass
time.sleep(.5)
assert not missions(),'mission process remains'
PY
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$here/../patches/build_v2.sh" "$condition" "$backup"
if [[ "$reset_mode" == no-reset ]]; then
  echo "CONDITION_SOURCE_READY=$condition"
  exit 0
fi
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
exec bash /home/ubuntu/tcei_hit_balloon_v2_tools/reset_scene_checked.sh
