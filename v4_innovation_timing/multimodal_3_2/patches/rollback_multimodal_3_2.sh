#!/usr/bin/env bash
# Restore only this experiment's two changed baseline files and added plugin.
# The caller must first follow AGENTS.md's shared-server occupancy check.
set -euo pipefail
BACKUP="${1:-/home/ubuntu/multimodal_3_2_backup_20261023T224616}"
MISSION=/home/ubuntu/model/mission_once.py
BT=/home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp
NEW_H=/home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/perception/multimodal_target_tracker.h
NEW_CPP=/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp
PLUGIN=/home/ubuntu/catkin_ws/devel/lib/multimodal_target_tracker.so
[ ! -e /tmp/tcei_formal_trial.lock ]
[ -z "$(pgrep -x bt_ros || true)" ] || { echo 'bt_ros active; refusing rollback' >&2; exit 1; }
check() { [ "$(md5sum "$1" | cut -d' ' -f1)" = "$2" ] || { echo "MD5 mismatch: $1" >&2; exit 1; }; }
check "$BACKUP/mission_once.py" fca24bf1142ca8cddfb9e8d39c387a43
check "$BACKUP/bt_ros.cpp" 9b1cefe9dfa431418435f7f8f63a60ed
case "$(md5sum "$MISSION" | cut -d' ' -f1)" in
  fca24bf1142ca8cddfb9e8d39c387a43|9e59ada4270b086f15e6133dc854cedb) ;;
  *) echo 'Unexpected live mission version; preserve and review it first' >&2; exit 1;;
esac
case "$(md5sum "$BT" | cut -d' ' -f1)" in
  9b1cefe9dfa431418435f7f8f63a60ed|9a1e8d2a5913968b1c2300cad1dc02f7) ;;
  *) echo 'Unexpected live BT version; preserve and review it first' >&2; exit 1;;
esac
if [ -e "$NEW_H" ]; then check "$NEW_H" edd5df5c1d3b1c14e592e540bc0f492e; fi
if [ -e "$NEW_CPP" ]; then check "$NEW_CPP" 8b7ec875aba50f1d0b02d5ce311f9e3c; fi
cp -p "$MISSION" "$BACKUP/mission_once.before_restore_$(date +%Y%m%dT%H%M%S).py"
cp -p "$BT" "$BACKUP/bt_ros.before_restore_$(date +%Y%m%dT%H%M%S).cpp"
cp -p "$BACKUP/mission_once.py" "$MISSION"
cp -p "$BACKUP/bt_ros.cpp" "$BT"
rm -f "$NEW_H" "$NEW_CPP"
if [ -e "$PLUGIN" ]; then
  md5sum "$PLUGIN"
  mv "$PLUGIN" "$BACKUP/multimodal_target_tracker.retired_$(date +%Y%m%dT%H%M%S).so"
fi
# cp -p preserves old timestamps. Force the restored source to rebuild;
# --force-cmake alone does not make a newer object file stale.
touch "$BT"
set +u
source /opt/ros/noetic/setup.bash
set -u
cd /home/ubuntu/catkin_ws
catkin_make --force-cmake --pkg mission_pkg -j2
check "$MISSION" fca24bf1142ca8cddfb9e8d39c387a43
check "$BT" 9b1cefe9dfa431418435f7f8f63a60ed
if strings devel/lib/mission_pkg/bt_ros | grep -F '<MultimodalTargetTracker' > /dev/null; then
  echo 'Binary still contains the candidate XML node; rollback incomplete' >&2; exit 1
fi
strings devel/lib/mission_pkg/bt_ros | grep -F '<TargetTracker object_name'
test ! -e "$PLUGIN"
echo 'rollback complete; no simulation or trial started'
