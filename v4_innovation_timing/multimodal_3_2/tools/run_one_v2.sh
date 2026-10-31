#!/usr/bin/env bash
# One unchanged official trial, independent read-only audit, post-flight evidence.
set -euo pipefail
color="${1:?red|purple|blue}"
condition="${2:?candidate|baseline}"
session="${3:?new output directory}"
case "$color" in red|purple|blue) ;; *) exit 2;; esac
case "$condition" in candidate|baseline) ;; *) exit 2;; esac
test ! -e /tmp/tcei_formal_trial.lock
test ! -e "$session"
mkdir -p "$session"
set +u
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
export MULTIMODAL_EVIDENCE_ROOT="$session/model"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 /home/ubuntu/tcei_hit_balloon_v2_tools/scene_snapshot.py before "$session"
python3 - "$session" <<'PY'
import json,sys
from pathlib import Path
row=json.loads((Path(sys.argv[1])/'scene_snapshots.jsonl').read_text().splitlines()[0])
assert row['reported_count']==3, row
PY
md5sum /home/ubuntu/model/mission_once.py /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch > "$session/deployed_md5.txt"
printf 'color=%s\ncondition=%s\n' "$color" "$condition" > "$session/condition.env"
/usr/bin/python3 -u "$here/observe_trial_v2.py" "$session/audit" > "$session/audit.log" 2>&1 &
observer=$!
cleanup() { kill -TERM "$observer" 2>/dev/null || true; wait "$observer" 2>/dev/null || true; }
trap cleanup EXIT
for ((i=0;i<30;i++)); do
  test ! -e "$session/audit/ready" || break
  kill -0 "$observer"
  sleep 1
done
test -e "$session/audit/ready"
set +e
bash /home/ubuntu/tcei_baseline_tools/run_formal_trial.sh "$color" > "$session/formal_runner.out" 2>&1
formal_rc=$?
set -e
printf '%s\n' "$formal_rc" > "$session/formal_exit_code"
trial="$(sed -n 's/^experiment_dir=//p' "$session/formal_runner.out" | tail -1)"
test -n "$trial" && test -d "$trial"
printf '%s\n' "$trial" > "$session/trial_path.txt"
# Only recovery after an own, completed official run. Record it separately.
state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
if ! grep -q 'armed: False' <<< "$state"; then
  printf '%s\n' "$state" > "$session/recovery_required.txt"
  timeout 8 rosservice call /mavros/cmd/land '{min_pitch: 0.0, yaw: 0.0, latitude: 0.0, longitude: 0.0, altitude: 0.0}' \
    > "$session/recovery_response.txt"
  for ((i=0;i<45;i++)); do
    sleep 1
    state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
    if grep -q 'armed: False' <<< "$state"; then break; fi
  done
fi
grep -q 'armed: False' <<< "$state"
/usr/bin/python3 "$here/postflight_snapshot_v2.py" "$session" > "$session/postflight_snapshot.out"
printf 'session=%s\ntrial=%s\nformal_rc=%s\n' "$session" "$trial" "$formal_rc"
echo 'EVIDENCE_COMPLETE=1'
