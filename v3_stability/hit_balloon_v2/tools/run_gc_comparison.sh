#!/usr/bin/env bash
# A separate control and forced-GC formal trial, each starting with 3 actors.
# Start detached only after the fresh-scene baseline loop has completed.
set -Eeuo pipefail
tools="${TCEI_HIT_V2_TOOLS:-/home/ubuntu/tcei_hit_balloon_v2_tools}"
output="${TCEI_GC_COMPARISON_OUTPUT:-/home/ubuntu/tcei_baseline_tools/results/balloon_gc_comparison_$(date +%Y%m%dT%H%M%S)}"
mkdir -p "$output"
trap 'echo "$?" > "$output/exit_code"' EXIT
set +u
source /opt/ros/noetic/setup.bash
set -u

check_idle() {
  test ! -e /tmp/tcei_formal_trial.lock
  timeout 8 rostopic echo -n 1 /mavros/state | grep -q 'armed: False'
}

recover_after_own_trial() {
  test ! -e /tmp/tcei_formal_trial.lock
  local state response
  state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
  if grep -q 'armed: False' <<< "$state"; then return; fi
  echo 'own GC comparison trial left PX4 armed; requesting AUTO.LAND' >> "$output/progress.log"
  response="$(timeout 8 rosservice call /mavros/cmd/land 'min_pitch: 0.0
yaw: 0.0
latitude: 0.0
longitude: 0.0
altitude: 0.0')"
  grep -q 'success: True' <<< "$response"
  for ((i=0; i<30; i++)); do
    sleep 1
    state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
    if grep -q 'armed: False' <<< "$state"; then return; fi
  done
  echo 'PX4 remained armed; stopping before reset' >&2
  exit 8
}

actor_count() {
  python3 - "$1" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1],encoding='utf-8') if x.strip()]
print(rows[-1]['reported_count'])
PY
}

for mode in ${TCEI_GC_MODES:-control gc}; do
  check_idle
  mkdir -p "$output/$mode/pre"
  python3 "$tools/scene_snapshot.py" before "$output/$mode/pre" > "$output/$mode/pre/snapshot.out"
  count="$(actor_count "$output/$mode/pre/scene_snapshots.jsonl")"
  if [[ "$count" != 3 ]]; then
    echo "$mode: actor count $count; reset" >> "$output/progress.log"
    check_idle
    setsid nohup bash "$tools/reset_scene_checked.sh" > "$output/$mode/reset.log" 2>&1 < /dev/null &
    reset_pid=$!
    wait "$reset_pid"
    grep -q 'environment_started=1' "$output/$mode/reset.log"
    check_idle
    python3 "$tools/scene_snapshot.py" after "$output/$mode/pre" > "$output/$mode/pre/post_reset.out"
    count="$(actor_count "$output/$mode/pre/scene_snapshots.jsonl")"
    [[ "$count" == 3 ]]
  fi
  echo "$mode: verified 3 actors" >> "$output/progress.log"
  TCEI_CAPTURE_REAL_FRAMES=1 TCEI_REQUIRE_FRESH_SCENE=1 \
    bash "$tools/run_with_scene_snapshots.sh" purple > "$output/$mode/wrapper.log" 2>&1 &
  wrapper_pid=$!
  session=""
  for ((i=0; i<120; i++)); do
    session="$(sed -n 's/^scene_session=//p' "$output/$mode/wrapper.log" | tail -1)"
    [[ -n "$session" && -e "$session/formal_runner.out" ]] && break
    kill -0 "$wrapper_pid" 2>/dev/null || break
    sleep 0.5
  done
  if [[ -z "$session" || ! -e "$session/formal_runner.out" ]]; then
    echo "$mode: wrapper did not start formal runner" >&2
    wait "$wrapper_pid" || true
    exit 7
  fi
  /usr/bin/python3 "$tools/gc_timing_probe.py" "$output/$mode" --mode "$mode" \
    --interval 1.5 --duration 450 --stop-file "$output/$mode/stop" \
    > "$output/$mode/monitor.log" 2>&1 &
  monitor_pid=$!
  for ((i=0; i<60; i++)); do
    [[ -e "$output/$mode/ready" ]] && break
    kill -0 "$monitor_pid" 2>/dev/null || break
    sleep 0.5
  done
  [[ -e "$output/$mode/ready" ]] || { echo "$mode: monitor failed" >&2; exit 8; }
  set +e
  wait "$wrapper_pid"
  wrapper_rc=$?
  set -e
  touch "$output/$mode/stop"
  wait "$monitor_pid"
  trial_dir="$(sed -n 's/^experiment_dir=//p' "$output/$mode/wrapper.log" | tail -1)"
  printf '%s\n' "$trial_dir" > "$output/$mode/trial_dir.txt"
  echo "$mode: wrapper_rc=$wrapper_rc trial=$trial_dir gc_commands=$(grep -c '"event": "gc_command"' "$output/$mode/events.jsonl" || true)" >> "$output/progress.log"
  recover_after_own_trial
done
