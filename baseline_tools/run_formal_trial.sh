#!/usr/bin/env bash
set -Eeuo pipefail

# Run exactly one official natural-language mission and observe its result.
# This script never publishes a mission or flight-control topic itself.

COLOR="${1:-}"
if [[ "$COLOR" != "red" && "$COLOR" != "purple" && "$COLOR" != "blue" ]]; then
  echo "usage: $0 <red|purple|blue>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="${TCEI_WS_ROOT:-/home/ubuntu/catkin_ws}"
MODEL_ROOT="${TCEI_MODEL_ROOT:-/home/ubuntu/model}"
MISSION_PYTHON_DIR="${TCEI_MISSION_PYTHON_DIR:-/opt/conda/envs/demo/bin}"
OBSERVER_PYTHON="${TCEI_OBSERVER_PYTHON:-/usr/bin/python3}"
RESULT_ROOT="${TCEI_TRIAL_ROOT:-${SCRIPT_DIR}/results/formal_trials}"
LOCK_DIR="${TCEI_TRIAL_LOCK_DIR:-/tmp/tcei_formal_trial.lock}"
PRE_MISSION_TIMEOUT="${TCEI_PRE_MISSION_TIMEOUT:-900}"
MISSION_TIMEOUT="${TCEI_MISSION_TIMEOUT:-300}"
MISSION_LAUNCH_TIMEOUT="${TCEI_MISSION_LAUNCH_TIMEOUT:-1200}"
V21_CONFIG="${TCEI_V21_CONFIG:-A0}"
V21_MAX_VEL="${TCEI_V21_MAX_VEL:-0.30}"

case "$COLOR" in
  red) TASK='飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击红色气球，完成后就回到起点并降落；' ;;
  purple) TASK='飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击紫色气球，完成后就回到起点并降落；' ;;
  blue) TASK='飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击蓝色气球，完成后就回到起点并降落；' ;;
esac

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "another formal trial is active or left an uncleared lock: $LOCK_DIR" >&2
  [[ -f "$LOCK_DIR/pid" ]] && echo "lock pid: $(cat "$LOCK_DIR/pid")" >&2
  exit 3
fi

EXPERIMENT_DIR="${RESULT_ROOT}/$(date +%Y%m%dT%H%M%S)_${COLOR}_${V21_CONFIG}"
mkdir -p "$EXPERIMENT_DIR/logs"
printf '%s\n' "$$" > "$LOCK_DIR/pid"
printf 'color=%s\nconfig=%s\nmax_vel=%s\ntask=%s\n' \
  "$COLOR" "$V21_CONFIG" "$V21_MAX_VEL" "$TASK" > "$EXPERIMENT_DIR/trial.env"
printf 'mission_python_dir=%s\n' "$MISSION_PYTHON_DIR" >> "$EXPERIMENT_DIR/trial.env"
printf 'observer_python=%s\n' "$OBSERVER_PYTHON" >> "$EXPERIMENT_DIR/trial.env"

observer_pid=""
mission_pid=""
cleanup_done=0

mission_pids() {
  # Count only the Python mission process.  The timeout wrapper and this
  # orchestration shell also contain mission_once.py in their argv; counting
  # them would falsely report multiple missions for one trial.
  ps -eo pid=,comm=,args= 2>/dev/null | awk '
    $2 ~ /^python([0-9.]*)?$/ &&
    $0 ~ /(^|[[:space:]\/])mission_once\.py([[:space:]]|$)/ { print $1 }
  '
}

mission_process_details() {
  ps -eo pid=,comm=,args= 2>/dev/null | awk '
    $2 ~ /^python([0-9.]*)?$/ &&
    $0 ~ /(^|[[:space:]\/])mission_once\.py([[:space:]]|$)/ { print }
  '
}

mission_family_pids() {
  # Include xterm/bash wrappers created by sim_env_start.sh as well as the
  # Python child, so a legacy interactive mission cannot survive into a trial.
  ps -eo pid=,args= 2>/dev/null | awk '
    $0 ~ /mission_once\.py([[:space:]]|$)/ { print $1 }
  '
}

mission_family_details() {
  ps -eo pid=,ppid=,comm=,args= 2>/dev/null | awk '
    $0 ~ /mission_once\.py([[:space:]]|$)/ { print }
  '
}

cleanup_old_mission_once() {
  local pids pid deadline
  pids="$(mission_family_pids)"
  [[ -z "$pids" ]] && return 0
  echo "stale mission_once.py processes found; terminating before this trial:" >&2
  mission_family_details >&2 || true
  while read -r pid; do
    [[ -z "$pid" ]] || kill -TERM "$pid" 2>/dev/null || true
  done <<< "$pids"
  deadline=$(( $(date +%s) + 10 ))
  while [[ -n "$(mission_family_pids)" && $(date +%s) -lt $deadline ]]; do sleep 1; done
  pids="$(mission_family_pids)"
  if [[ -n "$pids" ]]; then
    while read -r pid; do
      [[ -z "$pid" ]] || kill -KILL "$pid" 2>/dev/null || true
    done <<< "$pids"
    sleep 1
  fi
  if [[ -n "$(mission_family_pids)" ]]; then
    echo "cannot obtain a clean mission_once.py process state" >&2
    return 1
  fi
}

cleanup() {
  [[ "$cleanup_done" == 1 ]] && return
  cleanup_done=1
  if [[ -n "$mission_pid" ]] && kill -0 "$mission_pid" 2>/dev/null; then
    kill -TERM "$mission_pid" 2>/dev/null || true
    sleep 2
    kill -KILL "$mission_pid" 2>/dev/null || true
  fi
  if [[ -n "$observer_pid" ]] && kill -0 "$observer_pid" 2>/dev/null; then
    kill -TERM "$observer_pid" 2>/dev/null || true
    sleep 1
    kill -KILL "$observer_pid" 2>/dev/null || true
  fi
  # A command-line mission_once keeps its interactive loop alive after publish;
  # remove only that process family, never ROS or flight-control nodes.
  local pids
  pids="$(mission_family_pids)"
  if [[ -n "$pids" ]]; then
    while read -r pid; do
      [[ -z "$pid" ]] || kill -TERM "$pid" 2>/dev/null || true
    done <<< "$pids"
    sleep 2
  fi
  pids="$(mission_family_pids)"
  if [[ -n "$pids" ]]; then
    while read -r pid; do
      [[ -z "$pid" ]] || kill -KILL "$pid" 2>/dev/null || true
    done <<< "$pids"
  fi
  rm -rf "$LOCK_DIR"
}
trap cleanup EXIT
abort_trial() {
  echo "formal trial interrupted by operator" >&2
  exit 130
}
trap abort_trial INT TERM

if [[ -f /opt/ros/noetic/setup.bash ]]; then
  # shellcheck disable=SC1091
  set +u
  source /opt/ros/noetic/setup.bash
  set -u
else
  echo "ROS Noetic setup not found" >&2
  exit 2
fi
if [[ -f "$WS_ROOT/devel/setup.bash" ]]; then
  # shellcheck disable=SC1090
  set +u
  source "$WS_ROOT/devel/setup.bash"
  set -u
else
  echo "workspace setup not found: $WS_ROOT/devel/setup.bash" >&2
  exit 2
fi

echo "readiness: roscore"
rosnode list >/dev/null 2>&1 || { echo "roscore/ROS master is unavailable" >&2; exit 4; }
ros_nodes="$(rosnode list)"
ros_topics="$(rostopic list)"
echo "readiness: /mavros/state"
grep -Fxq '/mavros/state' <<< "$ros_topics" || { echo "/mavros/state is unavailable" >&2; exit 4; }
echo "readiness: /rflysim/uav1/local/odom publisher"
RFlySIM_ODOM_SAMPLE="$(timeout 10 rostopic echo -n 1 /rflysim/uav1/local/odom 2>/dev/null || true)"
grep -q '^pose:' <<< "$RFlySIM_ODOM_SAMPLE" || {
  echo "/rflysim/uav1/local/odom has no live message" >&2
  exit 4
}
echo "readiness: MAVROS connected"
MAVROS_STATE_SAMPLE="$(timeout 20 rostopic echo -n 1 /mavros/state 2>/dev/null || true)"
if ! grep -qi 'connected:[[:space:]]*true' <<< "$MAVROS_STATE_SAMPLE"; then
  echo "MAVROS is not connected" >&2
  exit 4
fi
echo "readiness: llm_mission_node"
grep -Fxq '/llm_mission_node' <<< "$ros_nodes" || { echo "llm_mission_node is unavailable" >&2; exit 4; }
echo "readiness: /objects"
grep -Fxq '/objects' <<< "$ros_topics" || { echo "/objects is unavailable" >&2; exit 4; }
echo "readiness: Ego-Planner nodes"
grep -Eq '^/(ego_planner_node|traj_server)$' <<< "$ros_nodes" || {
  echo "required planner nodes are unavailable" >&2
  exit 4
}

echo "preflight: pgrep -af mission_once.py"
pgrep -af '[m]ission_once\.py' || true
cleanup_old_mission_once
[[ -z "$(mission_pids)" ]] || { echo "mission_once.py cleanup verification failed" >&2; exit 5; }

echo "starting observer (pre_mission_timeout=${PRE_MISSION_TIMEOUT}s, mission_timeout=${MISSION_TIMEOUT}s)"
if [[ ! -x "$OBSERVER_PYTHON" ]]; then
  echo "observer Python runtime not found: $OBSERVER_PYTHON" >&2
  exit 5
fi
"$OBSERVER_PYTHON" -u "$SCRIPT_DIR/run_baseline.py" \
  --color "$COLOR" --no-launch-llm \
  --pre-mission-timeout "$PRE_MISSION_TIMEOUT" \
  --mission-timeout "$MISSION_TIMEOUT" \
  --v21-telemetry --v21-config "$V21_CONFIG" --v21-max-vel "$V21_MAX_VEL" \
  --logs-dir "$EXPERIMENT_DIR/logs" --v21-log-dir "$EXPERIMENT_DIR" \
  > "$EXPERIMENT_DIR/observer.out" 2>&1 &
observer_pid=$!

for _ in $(seq 1 120); do
  if grep -q 'Observer ready:' "$EXPERIMENT_DIR/observer.out"; then break; fi
  if ! kill -0 "$observer_pid" 2>/dev/null; then
    echo "observer exited before readiness" >&2
    exit 5
  fi
  sleep 0.5
done
grep -q 'Observer ready:' "$EXPERIMENT_DIR/observer.out" || {
  echo "observer did not become ready" >&2
  exit 5
}

if [[ ! -f "$MODEL_ROOT/mission_once.py" ]]; then
  echo "mission_once.py not found: $MODEL_ROOT/mission_once.py" >&2
  exit 5
fi
if [[ ! -x "$MISSION_PYTHON_DIR/python3" ]]; then
  echo "mission Python runtime not found: $MISSION_PYTHON_DIR/python3" >&2
  exit 5
fi
echo "starting official mission_once.py with argv task"
printf 'command: python3 mission_once.py "%s"\n' "$TASK"
(cd "$MODEL_ROOT" && timeout "$MISSION_LAUNCH_TIMEOUT" env "PATH=$MISSION_PYTHON_DIR:$PATH" \
  python3 mission_once.py "$TASK" </dev/null) \
  > "$EXPERIMENT_DIR/mission_once.out" 2>&1 &
mission_pid=$!

command_seen_in_log() {
  grep -R -q '"event": "mission_start"' "$EXPERIMENT_DIR/logs" 2>/dev/null
}

for _ in $(seq 1 $((PRE_MISSION_TIMEOUT * 2))); do
  count="$(mission_pids | wc -l | tr -d ' ')"
  [[ "$count" -le 1 ]] || { echo "expected at most one mission_once.py, found $count" >&2; exit 5; }
  if command_seen_in_log; then break; fi
  if ! kill -0 "$mission_pid" 2>/dev/null; then
    echo "mission_once.py exited before publishing /mission_command" >&2
    exit 5
  fi
  sleep 0.5
done
command_seen_in_log || { echo "mission_once.py did not produce /mission_command" >&2; exit 5; }

observer_rc=0
while kill -0 "$observer_pid" 2>/dev/null; do
  count="$(mission_pids | wc -l | tr -d ' ')"
  if [[ "$count" -gt 1 ]]; then
    echo "more than one mission_once.py detected during trial" >&2
    exit 5
  fi
  sleep 1
done
wait "$observer_pid" || observer_rc=$?
observer_pid=""

  if [[ -n "$(mission_family_pids)" ]]; then
  echo "mission_once.py still present after observer ended; cleanup will terminate it" >&2
fi
cleanup_old_mission_once
[[ -z "$(mission_pids)" ]] || { echo "mission_once.py residue remains after cleanup" >&2; exit 5; }
echo "mission_once_cleanup=OK"

echo "experiment_dir=$EXPERIMENT_DIR"
grep -E '^(PRE_MISSION_TIMEOUT|MISSION_TIMEOUT|csv=|raw_log=|\{|  "mission_success")' \
  "$EXPERIMENT_DIR/observer.out" | tail -20 || true

if grep -q '^PRE_MISSION_TIMEOUT:' "$EXPERIMENT_DIR/observer.out"; then
  exit 1
fi
if grep -q '"mission_success": "true"' "$EXPERIMENT_DIR/observer.out"; then
  exit 0
fi
[[ "$observer_rc" == 0 ]] && exit 1 || exit "$observer_rc"
