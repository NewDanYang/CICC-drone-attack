#!/usr/bin/env bash
set -u

for pattern in \
  '^xterm ' \
  '^/usr/bin/python3 /opt/ros/noetic/bin/roscore' \
  '^/usr/bin/python3 /opt/ros/noetic/bin/rosmaster' \
  '^/opt/ros/noetic/lib/mavros/mavros_node' \
  '^/home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros' \
  '^/home/ubuntu/catkin_ws/devel/lib/mission_pkg/aruco_detect_node' \
  '^bash ./start_sim_environment.sh' \
  '^bash /home/ubuntu/PX4PSP/SITLRun.sh'; do
  while read -r pid; do
    [ -n "$pid" ] && [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null || true
  done < <(pgrep -f "$pattern" || true)
done

for name in px4 CopterSim RflySim3D roscore rosmaster mavros_node bt_ros; do
  while read -r pid; do
    [ -n "$pid" ] && [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null || true
  done < <(pgrep -x "$name" || true)
done

sleep 3
for name in px4 CopterSim RflySim3D roscore rosmaster mavros_node bt_ros; do
  while read -r pid; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done < <(pgrep -x "$name" || true)
done

rm -f /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock /tmp/px4_lock-*
echo 'cleanup_done=1'
pgrep -x px4 || true
pgrep -x CopterSim || true
pgrep -x RflySim3D || true
pgrep -x roscore || true
pgrep -x rosmaster || true
pgrep -x mavros_node || true
pgrep -x bt_ros || true
ls -ld /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock /tmp/px4_lock-* 2>/dev/null || true
