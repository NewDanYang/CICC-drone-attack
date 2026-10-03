#!/usr/bin/env bash
set -Eeuo pipefail

# Start the shared simulation environment once per server/environment reset:
#   1. PX4/RflySim SITLRun.sh
#   2. wait 20 seconds for SITL initialization
#   3. catkin_ws/sim_env_start.sh
#
# This script does not start a mission and does not publish ROS control data.
# Run run_formal_trial.sh separately for each official natural-language trial.

PX4_ROOT="${TCEI_PX4_ROOT:-/home/ubuntu/PX4PSP}"
WS_ROOT="${TCEI_WS_ROOT:-/home/ubuntu/catkin_ws}"
SITL_SCRIPT="${TCEI_SITL_SCRIPT:-${PX4_ROOT}/SITLRun.sh}"
SIM_SCRIPT="${TCEI_SIM_SCRIPT:-${WS_ROOT}/sim_env_start.sh}"
STATE_DIR="${TCEI_SIM_STATE_DIR:-/tmp/tcei_sim_environment}"
LOCK_DIR="${TCEI_SIM_LOCK_DIR:-/tmp/tcei_sim_environment.lock}"
SITL_STARTUP_DELAY="${TCEI_SITL_STARTUP_DELAY:-20}"
ENV_READY_TIMEOUT="${TCEI_ENV_READY_TIMEOUT:-240}"
MAVROS_START_TIMEOUT="${TCEI_MAVROS_START_TIMEOUT:-60}"
MAVROS_CONNECTED_TIMEOUT="${TCEI_MAVROS_CONNECTED_TIMEOUT:-60}"
MAVROS_FCU_URL="${TCEI_MAVROS_FCU_URL:-udp://:20101@}"
ROS_HOME_DIR="${TCEI_ROS_HOME_DIR:-${STATE_DIR}/ros_home}"
RFLYSIM_SDK_ROOT="${TCEI_RFLYSIM_SDK_ROOT:-${PX4_ROOT}/RflySimAPIs/RflySimSDK}"
RFLY3D_ROOT="${TCEI_RFLY3D_ROOT:-${PX4_ROOT}/RflySimUE5/RflySim3D/Binaries/Linux}"
RFLY3D_USER="${TCEI_RFLY3D_USER:-ubuntu}"
RFLY3D_START_TIMEOUT="${TCEI_RFLY3D_START_TIMEOUT:-60}"
RFLY3D_DISPLAY="${TCEI_RFLY3D_DISPLAY:-${DISPLAY:-:20}}"

mkdir -p "$STATE_DIR"

if [[ ! -f "$SITL_SCRIPT" ]]; then
  echo "SITL script not found: $SITL_SCRIPT" >&2
  exit 2
fi
if [[ ! -f "$SIM_SCRIPT" ]]; then
  echo "simulation startup script not found: $SIM_SCRIPT" >&2
  exit 2
fi
if [[ ! -x "$RFLY3D_ROOT/RflySim3D" ]]; then
  echo "RflySim3D binary not found or not executable: $RFLY3D_ROOT/RflySim3D" >&2
  exit 2
fi

pid_alive() {
  [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null
}

if [[ -d "$LOCK_DIR" ]]; then
  old_sitl_pid="$(cat "$LOCK_DIR/sitl_pid" 2>/dev/null || true)"
  old_sim_pid="$(cat "$LOCK_DIR/sim_pid" 2>/dev/null || true)"
  old_mavros_pid="$(cat "$LOCK_DIR/mavros_pid" 2>/dev/null || true)"
  old_rfly3d_pid="$(cat "$LOCK_DIR/rfly3d_pid" 2>/dev/null || true)"
  if pid_alive "$old_sitl_pid" || pid_alive "$old_sim_pid" || pid_alive "$old_mavros_pid" || pid_alive "$old_rfly3d_pid"; then
    echo "simulation environment is already running: $LOCK_DIR" >&2
    [[ -n "$old_sitl_pid" ]] && echo "SITL pid: $old_sitl_pid" >&2
    [[ -n "$old_sim_pid" ]] && echo "sim_env pid: $old_sim_pid" >&2
    [[ -n "$old_mavros_pid" ]] && echo "MAVROS pid: $old_mavros_pid" >&2
    [[ -n "$old_rfly3d_pid" ]] && echo "RflySim3D pid: $old_rfly3d_pid" >&2
    exit 3
  fi
  echo "removing stale simulation environment lock (recorded processes are gone)"
  rm -f "$LOCK_DIR/pid" "$LOCK_DIR/sitl_pid" "$LOCK_DIR/sim_pid" "$LOCK_DIR/mavros_pid" "$LOCK_DIR/rfly3d_pid"
  rmdir "$LOCK_DIR" 2>/dev/null || {
    echo "cannot clear stale lock: $LOCK_DIR" >&2
    exit 3
  }
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "simulation environment lock already exists: $LOCK_DIR" >&2
  [[ -f "$LOCK_DIR/pid" ]] && echo "lock pid: $(cat "$LOCK_DIR/pid")" >&2
  exit 3
fi

SITL_PID=""
SIM_PID=""
MAVROS_PID=""
RFLY3D_PID=""
CLEANUP_DONE=0

cleanup() {
  [[ "$CLEANUP_DONE" == 1 ]] && return
  CLEANUP_DONE=1
  # The environment is intentionally long-lived.  On a normal exit, leave
  # both process trees running and retain the state directory for inspection.
  # On an interrupt before hand-off, terminate only the process this wrapper
  # started and remove its lock so a clean retry is possible.
  if [[ "${STARTUP_HANDOFF:-0}" != 1 ]]; then
    [[ -n "$SIM_PID" ]] && kill -TERM "$SIM_PID" 2>/dev/null || true
    if [[ -n "$SITL_PID" ]]; then
      kill -TERM -- "-$SITL_PID" 2>/dev/null || kill -TERM "$SITL_PID" 2>/dev/null || true
    fi
    if [[ -n "$MAVROS_PID" ]]; then
      kill -TERM -- "-$MAVROS_PID" 2>/dev/null || kill -TERM "$MAVROS_PID" 2>/dev/null || true
    fi
    sleep 1
    [[ -n "$SIM_PID" ]] && kill -KILL "$SIM_PID" 2>/dev/null || true
    if [[ -n "$SITL_PID" ]]; then
      kill -KILL -- "-$SITL_PID" 2>/dev/null || kill -KILL "$SITL_PID" 2>/dev/null || true
    fi
    if [[ -n "$MAVROS_PID" ]]; then
      kill -KILL -- "-$MAVROS_PID" 2>/dev/null || kill -KILL "$MAVROS_PID" 2>/dev/null || true
    fi
    if [[ -n "$RFLY3D_PID" ]]; then
      kill -TERM "$RFLY3D_PID" 2>/dev/null || true
      sleep 1
      kill -KILL "$RFLY3D_PID" 2>/dev/null || true
    fi
    rm -f "$LOCK_DIR/pid" "$LOCK_DIR/sitl_pid" "$LOCK_DIR/sim_pid" "$LOCK_DIR/mavros_pid" "$LOCK_DIR/rfly3d_pid"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
}
trap cleanup EXIT

abort_startup() {
  echo "simulation startup interrupted before environment hand-off" >&2
  exit 130
}
trap abort_startup INT TERM

# Make ROS CLI tools available for the post-launch readiness check.  The
# official sim_env_start.sh sources the workspace in its own child shell; this
# wrapper needs the same environment in the parent shell as well.
if [[ -f /opt/ros/noetic/setup.bash ]]; then
  # shellcheck disable=SC1091
  set +u
  source /opt/ros/noetic/setup.bash
  set -u
else
  echo "ROS Noetic setup not found: /opt/ros/noetic/setup.bash" >&2
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

printf '%s\n' "$$" > "$LOCK_DIR/pid"
printf 'px4_root=%s\nworkspace=%s\nsitl_script=%s\nsim_script=%s\nstarted_at=%s\n' \
  "$PX4_ROOT" "$WS_ROOT" "$SITL_SCRIPT" "$SIM_SCRIPT" "$(date -Is)" > "$STATE_DIR/startup.env"

# sim_env_start.sh launches Python ROS nodes from login shells.  The server's
# root .bashrc auto-activates Conda base, whose python3 lacks the ROS sensor
# dependencies (yaml/numpy/cv2).  Give those shells a clean HOME and a stable
# system ROS Python path; the formal mission runner selects the demo runtime
# separately for mission_once.py.
mkdir -p "$ROS_HOME_DIR"
: > "$ROS_HOME_DIR/.bash_profile"
: > "$ROS_HOME_DIR/.profile"
: > "$ROS_HOME_DIR/.bashrc"

echo "[1/2] starting SITL: $SITL_SCRIPT"
(
  cd "$PX4_ROOT"
  # SITLRun.sh waits for an interactive final read and otherwise cleans up
  # PX4 as soon as SSH supplies EOF. Keep its stdin open for the shared
  # environment lifetime without sending any input.
  exec setsid bash -c 'tail -f /dev/null | bash "$1"' _ "$SITL_SCRIPT"
) >"$STATE_DIR/sitl.out" 2>&1 &
SITL_PID=$!
printf '%s\n' "$SITL_PID" > "$LOCK_DIR/sitl_pid"
echo "SITL wrapper pid=$SITL_PID log=$STATE_DIR/sitl.out"

echo "waiting ${SITL_STARTUP_DELAY}s before starting sim_env_start.sh"
sleep "$SITL_STARTUP_DELAY"
if ! kill -0 "$SITL_PID" 2>/dev/null; then
  echo "SITLRun.sh exited during startup delay; inspect $STATE_DIR/sitl.out" >&2
  exit 4
fi
echo "[OK] SITL startup delay complete"

# SITLRun.sh invokes RflySim3D as root, but the packaged binary refuses root
# privileges. Start it as the regular simulation user when the official
# attempt did not leave a live process. This is launch orchestration only.
echo "checking RflySim3D"
if ! pgrep -x RflySim3D >/dev/null 2>&1; then
  if ! id "$RFLY3D_USER" >/dev/null 2>&1; then
    echo "RflySim3D user does not exist: $RFLY3D_USER" >&2
    exit 4
  fi
  echo "RflySim3D is absent; starting it as $RFLY3D_USER on DISPLAY=$RFLY3D_DISPLAY"
  (
    exec setsid runuser -u "$RFLY3D_USER" -- env \
      DISPLAY="$RFLY3D_DISPLAY" HOME="$(getent passwd "$RFLY3D_USER" | cut -d: -f6)" \
      LD_LIBRARY_PATH="/opt/gstreamer/lib/x86_64-linux-gnu:${PX4_ROOT}/QGroundControl/squashfs-root/Qt/libs:${RFLY3D_ROOT}" \
      bash -c 'cd "$1" && exec ./RflySim3D' _ "$RFLY3D_ROOT"
  ) >"$STATE_DIR/rflysim3d.out" 2>&1 &
  sleep 2
  RFLY3D_PID="$(pgrep -n -x RflySim3D || true)"
  [[ -n "$RFLY3D_PID" ]] && printf '%s\n' "$RFLY3D_PID" > "$LOCK_DIR/rfly3d_pid"
else
  echo "[OK] RflySim3D already exists"
fi

rfly3d_deadline=$(( $(date +%s) + RFLY3D_START_TIMEOUT ))
while [[ $(date +%s) -lt $rfly3d_deadline ]]; do
  if pgrep -x RflySim3D >/dev/null 2>&1; then
    echo "[OK] RflySim3D is running"
    break
  fi
  sleep 1
done
if ! pgrep -x RflySim3D >/dev/null 2>&1; then
  echo "RflySim3D did not become ready; inspect $STATE_DIR/rflysim3d.out" >&2
  exit 4
fi

echo "[2/2] starting simulation environment: $SIM_SCRIPT"
(
  # Detach the long-lived ROS environment from the SSH session.  Without a
  # separate session, closing the startup shell can deliver SIGHUP to roscore
  # and leave the simulation graph half alive.
  export HOME="$ROS_HOME_DIR"
  export PATH="/opt/conda/envs/demo/bin:/opt/ros/noetic/bin:/usr/bin:/bin"
  export CONDA_AUTO_ACTIVATE_BASE=false
  if [[ -d "$RFLYSIM_SDK_ROOT" ]]; then
    export PYTHONPATH="$RFLYSIM_SDK_ROOT:$RFLYSIM_SDK_ROOT/comm:$RFLYSIM_SDK_ROOT/ctrl:$RFLYSIM_SDK_ROOT/ue:$RFLYSIM_SDK_ROOT/vision:$RFLYSIM_SDK_ROOT/phm:$RFLYSIM_SDK_ROOT/swarm:$RFLYSIM_SDK_ROOT/adb:$RFLYSIM_SDK_ROOT/wsl:$RFLYSIM_SDK_ROOT/test:$RFLYSIM_SDK_ROOT/word${PYTHONPATH:+:$PYTHONPATH}"
  else
    echo "warning: RflySim SDK not found: $RFLYSIM_SDK_ROOT" >&2
  fi
  exec setsid bash -c 'cd "$1" && exec bash "$2"' _ "$WS_ROOT" "$SIM_SCRIPT"
) >"$STATE_DIR/sim_env.out" 2>&1 &
SIM_PID=$!
printf '%s\n' "$SIM_PID" > "$LOCK_DIR/sim_pid"
echo "sim_env_start.sh wrapper pid=$SIM_PID log=$STATE_DIR/sim_env.out"

# Wait for the core ROS graph and the real RflySim odometry publisher before
# checking MAVROS. The official sim_env_start.sh has its MAVROS launch line
# commented out, so /mavros/state may not exist at this point.
rflysim_odom_ready() {
  local odom_sample
  odom_sample="$(timeout 5 rostopic echo -n 1 /rflysim/uav1/local/odom 2>/dev/null || true)"
  grep -q '^pose:' <<< "$odom_sample"
}

echo "waiting for ROS environment and /rflysim/uav1/local/odom readiness (timeout ${ENV_READY_TIMEOUT}s)"
env_deadline=$(( $(date +%s) + ENV_READY_TIMEOUT ))
while [[ $(date +%s) -lt $env_deadline ]]; do
  if ! kill -0 "$SIM_PID" 2>/dev/null; then
    echo "sim_env_start.sh exited; inspect $STATE_DIR/sim_env.out" >&2
    exit 5
  fi
  if command -v rostopic >/dev/null 2>&1 && \
     rostopic list >/dev/null 2>&1 && \
     rflysim_odom_ready; then
    echo "[OK] ROS graph and RflySim odom publisher are ready"
    break
  fi
  sleep 2
done
if ! command -v rostopic >/dev/null 2>&1 || \
   ! rostopic list >/dev/null 2>&1 || \
   ! rflysim_odom_ready; then
  echo "timed out waiting for ROS graph/RflySim odom; inspect $STATE_DIR/sim_env.out" >&2
  exit 5
fi

# sim_env_start.sh intentionally leaves its MAVROS launch line commented out.
# Check for an already-running MAVROS first; otherwise launch the same PX4
# UDP bridge used by the official configuration.  This is orchestration only.
echo "checking MAVROS node"
if ! rosnode list 2>/dev/null | grep -Fxq '/mavros'; then
  echo "MAVROS node is absent; starting roslaunch mavros px4.launch"
  (
    exec setsid bash -c \
      'set +u; source /opt/ros/noetic/setup.bash; source "$1/devel/setup.bash"; exec roslaunch mavros px4.launch "fcu_url:=$2"' \
      _ "$WS_ROOT" "$MAVROS_FCU_URL"
  ) >"$STATE_DIR/mavros.out" 2>&1 &
  MAVROS_PID=$!
  printf '%s\n' "$MAVROS_PID" > "$LOCK_DIR/mavros_pid"
  echo "MAVROS wrapper pid=$MAVROS_PID log=$STATE_DIR/mavros.out"
else
  echo "[OK] MAVROS node already exists"
fi

mavros_connected() {
  local state_sample
  state_sample="$(timeout 5 rostopic echo -n 1 /mavros/state 2>/dev/null || true)"
  grep -qi 'connected:[[:space:]]*true' <<< "$state_sample"
}

echo "waiting for MAVROS node (timeout ${MAVROS_START_TIMEOUT}s)"
mavros_deadline=$(( $(date +%s) + MAVROS_START_TIMEOUT ))
while [[ $(date +%s) -lt $mavros_deadline ]]; do
  if rosnode list 2>/dev/null | grep -Fxq '/mavros'; then break; fi
  sleep 1
done
if ! rosnode list 2>/dev/null | grep -Fxq '/mavros'; then
  echo "MAVROS node did not become visible; inspect $STATE_DIR/mavros.out" >&2
  exit 6
fi

echo "waiting for MAVROS connected=true (timeout ${MAVROS_CONNECTED_TIMEOUT}s)"
mavros_connected_deadline=$(( $(date +%s) + MAVROS_CONNECTED_TIMEOUT ))
while [[ $(date +%s) -lt $mavros_connected_deadline ]]; do
  if mavros_connected; then
    echo "[OK] MAVROS connected"
    break
  fi
  sleep 1
done
if ! mavros_connected; then
  echo "MAVROS did not report connected=true; inspect $STATE_DIR/mavros.out" >&2
  exit 6
fi

# From this point onward the environment is intentionally long-lived.  Keep
# the lock and process records so a second startup cannot create duplicates.
STARTUP_HANDOFF=1

cat > "$STATE_DIR/README.txt" <<EOF
The shared environment was started by start_sim_environment.sh.
SITL log: $STATE_DIR/sitl.out
sim_env log: $STATE_DIR/sim_env.out
Do not run this startup script again for each color trial.
Run baseline_tools/run_formal_trial.sh <red|purple|blue> after readiness checks.
EOF

echo "environment_started=1"
echo "state_dir=$STATE_DIR"
echo "Run one trial at a time with: run_formal_trial.sh <red|purple|blue>"

# The wrapper has handed ownership to the long-lived process trees.  Keep the
# lock and PID records so a second startup cannot create duplicate environments.
trap - EXIT INT TERM
exit 0
