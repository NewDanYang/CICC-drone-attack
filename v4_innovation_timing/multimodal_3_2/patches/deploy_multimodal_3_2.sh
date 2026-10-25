#!/usr/bin/env bash
# Historical reproduction only. The tested candidate is known to ignore images.
set -euo pipefail
if [ "${1:-}" != --reproduce-rejected-candidate ]; then
  echo 'REJECTED: this is an audit snapshot, not a deployable 3.2 solution.' >&2
  echo 'No files changed. See REPORT.md and REJECTED.md.' >&2
  exit 2
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
MISSION=/home/ubuntu/model/mission_once.py
BT=/home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp
NEW_H=/home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/perception/multimodal_target_tracker.h
NEW_CPP=/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp
PLUGIN=/home/ubuntu/catkin_ws/devel/lib/multimodal_target_tracker.so
for lock in /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock; do
  [ ! -e "$lock" ] || { echo "Review shared-server occupancy first: $lock" >&2; exit 1; }
done
[ -z "$(pgrep -x bt_ros || true)" ] || { echo 'bt_ros active; refusing' >&2; exit 1; }
[ ! -e "$NEW_H" ] && [ ! -e "$NEW_CPP" ] && [ ! -e "$PLUGIN" ]
check() { [ "$(md5sum "$1" | cut -d' ' -f1)" = "$2" ] || { echo "MD5 mismatch: $1" >&2; exit 1; }; }
check "$MISSION" fca24bf1142ca8cddfb9e8d39c387a43
check "$BT" 9b1cefe9dfa431418435f7f8f63a60ed
check "$ROOT/staging/mission_once.py" 9e59ada4270b086f15e6133dc854cedb
check "$ROOT/source/mission_pkg/include/nodes/perception/multimodal_target_tracker.h" edd5df5c1d3b1c14e592e540bc0f492e
check "$ROOT/source/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp" 8b7ec875aba50f1d0b02d5ce311f9e3c
BACKUP="/home/ubuntu/multimodal_3_2_backup_$(date +%Y%m%dT%H%M%S)"
mkdir "$BACKUP"
cp -p "$MISSION" "$BACKUP/mission_once.py"
cp -p "$BT" "$BACKUP/bt_ros.cpp"
cp -p /home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros "$BACKUP/bt_ros.binary"
cp "$HERE/rollback_multimodal_3_2.sh" "$BACKUP/restore.sh"
python3 "$HERE/patch_bt_ros_multimodal.py" "$BT" "$BACKUP/bt_ros.candidate.cpp" \
  --expected-md5 9b1cefe9dfa431418435f7f8f63a60ed
check "$BACKUP/bt_ros.candidate.cpp" 9a1e8d2a5913968b1c2300cad1dc02f7
cp "$ROOT/staging/mission_once.py" "$MISSION"
cp "$ROOT/source/mission_pkg/include/nodes/perception/multimodal_target_tracker.h" "$NEW_H"
cp "$ROOT/source/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp" "$NEW_CPP"
cp "$BACKUP/bt_ros.candidate.cpp" "$BT"
/opt/conda/envs/demo/bin/python3 -m py_compile "$MISSION"
touch "$BT" "$NEW_CPP" "$NEW_H"
set +u
source /opt/ros/noetic/setup.bash
set -u
cd /home/ubuntu/catkin_ws
catkin_make --force-cmake --pkg mission_pkg -j2
strings devel/lib/mission_pkg/bt_ros | grep -F '<MultimodalTargetTracker object_name'
test -f "$PLUGIN"
echo "Rejected snapshot reproduced; no flight started. Rollback: bash '$BACKUP/restore.sh' '$BACKUP'"
