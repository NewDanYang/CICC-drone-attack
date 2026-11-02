#!/usr/bin/env bash
set -Eeuo pipefail

# --preflight checks dependencies without launching; --start delegates to the SITL wrapper.
# The foreground supervisor starts only the disarmed qualification ROS graph.
WS_ROOT="${TCEI_WS_ROOT:-/home/ubuntu/qualification_ws}"
UNDERLAY_WS="${TCEI_UNDERLAY_WS:-/home/ubuntu/catkin_ws}"
PX4_ROOT="${TCEI_PX4_ROOT:-/home/ubuntu/PX4PSP}"
SDK_ROOT="${TCEI_RFLYSIM_SDK_ROOT:-${PX4_ROOT}/RflySimAPIs/RflySimSDK}"
STATE_DIR="${TCEI_QUAL_STATE_DIR:-/tmp/tcei_qualification_nodes}"
ARUCO_SOURCE="${TCEI_QUAL_ARUCO_SOURCE:-}"
ARUCO_TARGET="${WS_ROOT}/src/mission_pkg/scripts/aruco_detect_node.py"
MISSION_LAUNCH="${WS_ROOT}/src/mission_pkg/launch/llm_mission.launch"
SYSTEM_PYTHON="${TCEI_SYSTEM_PYTHON:-/usr/bin/python3}"
ROS_SETUP="${TCEI_ROS_SETUP:-/opt/ros/noetic/setup.bash}"
SENSOR_PYTHON="${TCEI_SENSOR_PYTHON:-/opt/conda/envs/demo/bin/python3}"
MODE="${1:-}"
if [[ "$MODE" != "" && "$MODE" != "--preflight" && "$MODE" != "--start" ]]; then
  echo "usage: $0 [--preflight|--start]" >&2
  exit 2
fi
export ROS_MASTER_URI="${ROS_MASTER_URI:-http://127.0.0.1:11311}"
export ROS_IP="${ROS_IP:-127.0.0.1}"
export PSP_PATH="${PSP_PATH:-$PX4_ROOT}"
export DISPLAY="${DISPLAY:-:20}"
export XAUTHORITY="${XAUTHORITY:-/home/ubuntu/.Xauthority}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if [[ "$ROS_MASTER_URI" != http://127.0.0.1:11311 && "$ROS_MASTER_URI" != http://localhost:11311 ]]; then
  echo "qualification requires the simulation ROS master on localhost:11311 (mock tests use 11321): $ROS_MASTER_URI" >&2
  exit 2
fi
for required in "$ROS_SETUP" "$UNDERLAY_WS/devel/setup.bash" "$WS_ROOT/devel/setup.bash" \
  "$UNDERLAY_WS/src/sensor_pkg/main.py" "$UNDERLAY_WS/src/sensor_pkg/AgentContestMap.py" \
  "$UNDERLAY_WS/src/sensor_pkg/cloud_transform_node.py" \
  "$MISSION_LAUNCH" "$SDK_ROOT" "$SYSTEM_PYTHON" "$SENSOR_PYTHON"; do
  if [[ ! -e "$required" ]]; then echo "missing qualification dependency: $required" >&2; exit 2; fi
done
if [[ -z "$ARUCO_SOURCE" || ! -f "$ARUCO_SOURCE" ]]; then
  echo "set TCEI_QUAL_ARUCO_SOURCE to the reviewed candidate aruco_detect_node.py" >&2
  exit 2
fi
if [[ ! -f "$ARUCO_TARGET" ]]; then
  echo "isolated qualification mission_pkg lacks ArUco script: $ARUCO_TARGET" >&2
  exit 2
fi
if [[ ! "${TCEI_QUAL_ARUCO_SHA256:-}" =~ ^[[:xdigit:]]{64}$ ]] || \
   [[ "$(sha256sum "$ARUCO_SOURCE" | awk '{print $1}' | tr -d '\\')" != "${TCEI_QUAL_ARUCO_SHA256,,}" ]]; then
  echo "candidate ArUco SHA-256 does not match TCEI_QUAL_ARUCO_SHA256" >&2
  exit 2
fi
SITL_SCRIPT="${TCEI_SITL_SCRIPT:-$PX4_ROOT/SITLRun.sh}"
SIM_WRAPPER="${TCEI_SIM_WRAPPER:-$(realpath "$(dirname "${BASH_SOURCE[0]}")/../../../baseline_tools/start_sim_environment.sh")}"
RFLY3D_ROOT="${TCEI_RFLY3D_ROOT:-$PX4_ROOT/RflySimUE5/RflySim3D/Binaries/Linux}"
for script in "$SITL_SCRIPT" "$SIM_WRAPPER"; do
  [[ -f "$script" && -r "$script" ]] || { echo "missing readable startup script: $script" >&2; exit 2; }
done
[[ -x "$RFLY3D_ROOT/RflySim3D" ]] || { echo "missing executable simulator: $RFLY3D_ROOT/RflySim3D" >&2; exit 2; }
library_report="$(LD_LIBRARY_PATH="/opt/gstreamer/lib/x86_64-linux-gnu:${PX4_ROOT}/QGroundControl/squashfs-root/Qt/libs:${RFLY3D_ROOT}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "${TCEI_LDD:-ldd}" "$RFLY3D_ROOT/RflySim3D" 2>&1)" || {
  echo "cannot inspect RflySim3D shared libraries: $library_report" >&2; exit 2;
}
if grep -q 'not found' <<< "$library_report"; then
  echo "RflySim3D has missing shared libraries: $library_report" >&2
  exit 2
fi
[[ -n "$DISPLAY" ]] && command -v xdpyinfo >/dev/null && timeout 5 xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 || {
  echo "X display unavailable: $DISPLAY" >&2; exit 2;
}
[[ -r "$XAUTHORITY" ]] || { echo "X authority unavailable: $XAUTHORITY" >&2; exit 2; }
for dir in "$STATE_DIR" "$WS_ROOT"; do
  parent="$dir"
  while [[ ! -d "$parent" ]]; do parent="$(dirname "$parent")"; done
  [[ -w "$parent" ]] || { echo "storage not writable: $parent" >&2; exit 2; }
  available_kb="$(df -Pk "$parent" | tail -n 1 | awk '{print $4}')"
  [[ "$available_kb" =~ ^[0-9]+$ && "$available_kb" -ge 1048576 ]] || {
    echo "less than 1 GiB free at $parent" >&2; exit 2;
  }
done

set +u
source "$ROS_SETUP"
source "$UNDERLAY_WS/devel/setup.bash"
source "$WS_ROOT/devel/setup.bash"
set -u
export PATH="$PATH:/opt/ros/noetic/bin:/usr/bin:/bin"
export PYTHONPATH="$SDK_ROOT:$SDK_ROOT/comm:$SDK_ROOT/ctrl:$SDK_ROOT/ue:$SDK_ROOT/vision:$SDK_ROOT/phm:$SDK_ROOT/swarm:$SDK_ROOT/adb:$SDK_ROOT/wsl:$SDK_ROOT/test:$SDK_ROOT/word${PYTHONPATH:+:$PYTHONPATH}"
if ! (cd "$UNDERLAY_WS/src/sensor_pkg" && timeout 30 "$SENSOR_PYTHON" -c 'import cv2, numpy, scipy, pygame, rospy, sensor_msgs.point_cloud2, nav_msgs.msg, VisionCaptureApi, ReqCopterSim, RflyRosStart, PX4MavCtrlV4, UE4CtrlAPI'); then
  echo "sensor/map Python dependencies unavailable under $SENSOR_PYTHON" >&2
  exit 2
fi
if ! timeout 30 "$SYSTEM_PYTHON" -c 'import rospy, roslaunch, rospkg, cv2, numpy, sensor_msgs.msg, nav_msgs.msg, mavros_msgs.msg'; then
  echo "ROS launcher/mission dependencies unavailable under $SYSTEM_PYTHON" >&2
  exit 2
fi
for package in sensor_pkg ego_planner; do
  package_path="$(rospack find "$package")" || { echo "ROS package missing: $package" >&2; exit 2; }
  case "$package_path/" in
    "$UNDERLAY_WS/src/"*) ;;
    *) echo "unexpected $package package path: $package_path" >&2; exit 2 ;;
  esac
done
if [[ "$(rospack find object_det)" != "$WS_ROOT/src/object_det" ]]; then
  echo "object_det must resolve to isolated qualification workspace" >&2
  exit 2
fi
if [[ "$(rospack find mission_pkg)" != "$WS_ROOT/src/mission_pkg" ]]; then
  echo "mission_pkg must resolve to isolated qualification workspace" >&2
  exit 2
fi
for launch in "$MISSION_LAUNCH" "$WS_ROOT/src/mission_pkg/launch/aruco_detect.launch"; do
  "$SYSTEM_PYTHON" - "$launch" <<'PY' || exit 2
import sys
import xml.etree.ElementTree as ET
ET.parse(sys.argv[1])
PY
done
for spec in 'object_det detection_color.launch' 'ego_planner FS-J310_ego-planner.launch'; do
  read -r package launch <<< "$spec"
  launch_files="$(timeout 8 roslaunch --files "$package" "$launch")" || {
    echo "cannot resolve ROS launch: $package $launch" >&2; exit 2;
  }
  path="$(head -n 1 <<< "$launch_files")"
  [[ -r "$path" ]] || { echo "missing resolved ROS launch: $path" >&2; exit 2; }
  "$SYSTEM_PYTHON" - "$path" <<'PY' || exit 2
import sys
import xml.etree.ElementTree as ET
ET.parse(sys.argv[1])
PY
done
[[ -x "$WS_ROOT/devel/lib/mission_pkg/bt_ros" ]] || {
  echo "missing compiled mission node: $WS_ROOT/devel/lib/mission_pkg/bt_ros" >&2; exit 2;
}
mission_libraries="$("${TCEI_LDD:-ldd}" "$WS_ROOT/devel/lib/mission_pkg/bt_ros" 2>&1)" || {
  echo "cannot inspect mission node libraries: $mission_libraries" >&2; exit 2;
}
if grep -q 'not found' <<< "$mission_libraries"; then
  echo "mission node has missing libraries: $mission_libraries" >&2; exit 2;
fi
if [[ "$MODE" == "--preflight" || "$MODE" == "--start" ]]; then
  plugin_check="$(timeout 15 "$WS_ROOT/devel/lib/mission_pkg/bt_ros" --check-plugins 2>&1)" || {
    echo "mission plugin preflight failed: $plugin_check" >&2; exit 2;
  }
  if ! grep -q 'sequential_plugin_preflight_passed=1' <<< "$plugin_check"; then
    echo "mission binary lacks verified plugin preflight: $plugin_check" >&2; exit 2;
  fi
  if [[ -d "${TCEI_SIM_LOCK_DIR:-/tmp/tcei_sim_environment.lock}" ]]; then
    echo "simulation lock exists; inspect owned PIDs before any new start" >&2
    exit 3
  fi
  if [[ -f "$STATE_DIR/owner.pid" ]]; then
    echo "qualification supervisor state exists; inspect owned PID before any new start" >&2
    exit 3
  fi
fi
if [[ "$MODE" == "--preflight" ]]; then
  echo "qualification_preflight_passed=1; read-only; no SITL or ROS processes started"
  exit 0
fi
if [[ "$MODE" == "--start" ]]; then
  export TCEI_SIM_SCRIPT="$(realpath "${BASH_SOURCE[0]}")"
  echo "qualification_preflight_passed=1; starting outer wrapper once"
  exec bash "$SIM_WRAPPER"
fi

mkdir -p "$STATE_DIR"
if [[ -e "$STATE_DIR/owner.pid" ]] && kill -0 "$(<"$STATE_DIR/owner.pid")" 2>/dev/null; then
  echo "qualification node supervisor already running: $(<"$STATE_DIR/owner.pid")" >&2
  exit 3
fi
if timeout 3 rostopic list >/dev/null 2>&1; then
  for node in /llm_mission_node /aruco_detect_node /object_detection_node /ego_planner_node; do
    if rosnode list 2>/dev/null | grep -Fxq "$node"; then
      echo "ROS node already present; refusing to replace another graph: $node" >&2
      exit 3
    fi
  done
fi

# Copy only into the isolated overlay; preserve the previous bytes for rollback.
if ! cmp -s "$ARUCO_SOURCE" "$ARUCO_TARGET"; then
  cp -p "$ARUCO_TARGET" "$ARUCO_TARGET.bak_$(date +%Y%m%dT%H%M%S)"
  cp "$ARUCO_SOURCE" "$ARUCO_TARGET"
fi
sha256sum "$ARUCO_SOURCE" "$ARUCO_TARGET" "$MISSION_LAUNCH" > "$STATE_DIR/payload.sha256"
printf '%s\n' "$$" > "$STATE_DIR/owner.pid"

names=()
pids=()
cleanup() {
  trap - EXIT INT TERM
  if [[ ${#pids[@]} -gt 0 ]]; then
    if ! timeout 4 "$SYSTEM_PYTHON" -c 'import rospy; from mavros_msgs.msg import State; rospy.init_node("qualification_disarm_probe", anonymous=True, disable_signals=True); m=rospy.wait_for_message("/mavros/state", State, timeout=2); age=(rospy.Time.now()-m.header.stamp).to_sec(); assert m.connected and not m.armed and 0 <= age <= 2.5' >/dev/null 2>&1; then
      echo "FCU disarm not proven; leaving owned graph running for manual recovery" >&2
      return
    fi
  fi
  for ((i=${#pids[@]}-1; i>=0; i--)); do
    kill -TERM -- "-${pids[i]}" 2>/dev/null || true
  done
  sleep 1
  for ((i=${#pids[@]}-1; i>=0; i--)); do
    kill -KILL -- "-${pids[i]}" 2>/dev/null || true
    wait "${pids[i]}" 2>/dev/null || true
  done
  if [[ -f "$STATE_DIR/owner.pid" && "$(<"$STATE_DIR/owner.pid")" == "$$" ]]; then
    rm -f "$STATE_DIR/owner.pid"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

start() {
  local name="$1" dir="$2"
  shift 2
  (cd "$dir" && exec setsid "$@") >"$STATE_DIR/$name.out" 2>&1 &
  names+=("$name")
  pids+=("$!")
  echo "$name pid=${pids[-1]} log=$STATE_DIR/$name.out"
}
check_children() {
  local i
  for ((i=0; i<${#pids[@]}; i++)); do
    if ! kill -0 "${pids[i]}" 2>/dev/null; then
      echo "${names[i]} exited; inspect $STATE_DIR/${names[i]}.out" >&2
      return 1
    fi
  done
}

if ! timeout 3 rostopic list >/dev/null 2>&1; then
  start roscore "$WS_ROOT" roscore
  for ((i=0; i<30; i++)); do
    timeout 3 rostopic list >/dev/null 2>&1 && break
    check_children
    sleep 1
  done
  timeout 3 rostopic list >/dev/null 2>&1 || { echo "roscore unavailable" >&2; exit 4; }
else
  echo "using existing ROS master on $ROS_MASTER_URI"
fi

rosparam load "$WS_ROOT/src/object_det/config/detection_params.yaml" /object_detection
start detection "$WS_ROOT" roslaunch object_det detection_color.launch
start sensor "$UNDERLAY_WS/src/sensor_pkg" "$SENSOR_PYTHON" main.py
sleep 5
check_children
start map "$UNDERLAY_WS/src/sensor_pkg" "$SENSOR_PYTHON" AgentContestMap.py
sleep 3
check_children
start cloud "$UNDERLAY_WS/src/sensor_pkg" "$SENSOR_PYTHON" cloud_transform_node.py
start aruco "$WS_ROOT" roslaunch mission_pkg aruco_detect.launch show_debug:=false
start ego "$WS_ROOT" roslaunch ego_planner FS-J310_ego-planner.launch
start mission "$WS_ROOT" roslaunch "$MISSION_LAUNCH"
required_nodes=(/llm_mission_node /aruco_detect_node /object_detection_node /ego_planner_node /traj_server)
check_graph() {
  local node graph
  graph="$(timeout 3 rosnode list 2>/dev/null)" || return 1
  for node in "${required_nodes[@]}"; do
    grep -Fxq "$node" <<< "$graph" || return 1
    timeout 1 rosnode ping -c 1 "$node" >/dev/null 2>&1 || return 1
  done
}
ready=0
ready_deadline=$((SECONDS + ${TCEI_QUAL_READY_TIMEOUT:-90}))
while (( SECONDS < ready_deadline )); do
  check_children
  if check_graph && timeout 4 "$SYSTEM_PYTHON" -c 'import json, rospy; from std_msgs.msg import String; rospy.init_node("qualification_readiness_probe", anonymous=True, disable_signals=True); m=rospy.wait_for_message("/mission_ready", String, timeout=2); assert json.loads(m.data).get("state") == "IDLE"' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "qualification graph or IDLE mission heartbeat absent after bounded startup; inspect $STATE_DIR logs" >&2
  exit 4
fi

echo "qualification_nodes_started=1"
echo "no LLM, mission request, or arm command was sent by this launcher"
echo "logs=$STATE_DIR; supervisor pid=$$"
while true; do
  if ! check_children || ! check_graph; then
    echo "qualification graph degraded; do not restart a node in place; inspect flight state before stopping owned graph" >&2
    sleep 10
  else
    sleep 2
  fi
done
