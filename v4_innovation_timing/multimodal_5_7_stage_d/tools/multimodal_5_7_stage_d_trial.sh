#!/usr/bin/env bash
set -o pipefail

color="${1:?color}"
label="${2:?label}"
out_root="${3:?out_root}"
tools=/home/ubuntu/tcei_hit_balloon_v2_tools
base=/home/ubuntu/tcei_baseline_tools
session="$out_root/session_${label}"
mkdir -p "$session"

set +e
python3 "$tools/scene_snapshot.py" before "$session" > "$session/before.out" 2>&1
before_rc=$?
set -e
if [[ "$before_rc" != 0 ]]; then
  echo "before_snapshot_rc=$before_rc" > "$session/status.txt"
  exit 5
fi
before_count=$(python3 - "$session/scene_snapshots.jsonl" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1],encoding='utf-8') if x.strip()]
print(rows[-1]['reported_count'])
PY
)
if [[ "$before_count" != 3 ]]; then
  echo "before_count=$before_count" > "$session/status.txt"
  exit 5
fi

mkdir -p "$session/real_frames"
(
  set +u
  source /home/ubuntu/catkin_ws/devel/setup.bash
  set -u
  exec /usr/bin/python3 "$tools/capture_real_frames.py" "$session/real_frames"
) > "$session/frame_capture.out" 2>&1 &
capture_pid=$!
sleep 2

set +e
bash "$base/run_formal_trial.sh" "$color" > "$session/formal_runner.out" 2>&1
trial_rc=$?
set -e
kill -TERM "$capture_pid" 2>/dev/null || true
wait "$capture_pid" 2>/dev/null || true

trial_dir=$(sed -n 's/^experiment_dir=//p' "$session/formal_runner.out" | tail -1)
if [[ -z "$trial_dir" || ! -d "$trial_dir" ]]; then
  printf 'trial_rc=%s\ntrial_dir=\n' "$trial_rc" > "$session/status.txt"
  exit "$trial_rc"
fi

# The flight is over here. The first simulator object query is deliberately
# after the runner and after PX4 has disarmed. No GC or payload query occurs in
# the before/in-flight part of the trial.
set +e
/usr/bin/python3 - <<'PY' > "$session/post_gc.out" 2>&1
import sys
sys.path.insert(0, '/home/ubuntu/PX4PSP/RflySimAPIs/RflySimSDK/ue')
from UE4CtrlAPI import UE4CtrlAPI
UE4CtrlAPI().sendUE4Cmd('obj gc')
print('post_trial_gc_sent=1')
PY
gc_rc=$?
set -e
sleep 3
python3 "$tools/scene_snapshot.py" after "$session" > "$session/after.out" 2>&1 || true
sleep 15
python3 "$tools/scene_snapshot.py" late "$session" > "$session/late15.out" 2>&1 || true
sleep 30
python3 "$tools/scene_snapshot.py" late "$session" > "$session/late45.out" 2>&1 || true
sleep 45
python3 "$tools/scene_snapshot.py" late "$session" > "$session/late90.out" 2>&1 || true
sleep 35
python3 "$tools/scene_snapshot.py" settled "$session" > "$session/settled.out" 2>&1 || true

# Query surviving actor transforms only after the fixed settling window. The
# fixed lane mapping is applied later from this raw object list.
python3 "$tools/query_balloon_positions.py" "$session" > "$session/actor_positions.json" 2>&1 || true

cp "$session/scene_snapshots.jsonl" "$trial_dir/scene_snapshots.jsonl"
cp "$session/formal_runner.out" "$trial_dir/scene_runner.out"
cp "$session/post_gc.out" "$trial_dir/post_gc.out"
cp "$session/actor_positions.json" "$trial_dir/actor_positions.json"
cp "$session/frame_capture.out" "$trial_dir/frame_capture.out"
if [[ -d "$session/real_frames" ]]; then
  rm -rf "$trial_dir/real_frames"
  cp -a "$session/real_frames" "$trial_dir/real_frames"
fi
python3 "$tools/judge_hit.py" "$trial_dir" > "$trial_dir/judgement.json" 2>&1 || true

printf 'trial_rc=%s\ngc_rc=%s\nbefore_count=%s\ntrial_dir=%s\n' \
  "$trial_rc" "$gc_rc" "$before_count" "$trial_dir" > "$session/status.txt"
printf '%s\n' "$trial_dir" > "$session/trial_dir.txt"
sha256sum "$trial_dir"/scene_snapshots.jsonl "$trial_dir"/actor_positions.json \
  "$trial_dir"/observer.out "$trial_dir"/logs/*.jsonl 2>/dev/null > "$session/sha256.txt" || true
exit "$trial_rc"
