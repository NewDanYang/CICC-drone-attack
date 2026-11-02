#!/usr/bin/env bash
set -euo pipefail
exec 9>/tmp/tcei_multimodal_v2_build.lock
flock -n 9 || { echo 'Another multimodal build is active' >&2; exit 3; }
mode="${1:?candidate|baseline}"
backup="${2:?backup directory}"
case "$mode" in candidate|baseline) ;; *) exit 2;; esac
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 "$here/deploy_v2.py" "$mode" "$backup"
set +u
source /opt/ros/noetic/setup.bash
set -u
cd /home/ubuntu/catkin_ws
catkin_make --force-cmake --pkg mission_pkg -j2
/usr/bin/python3 "$here/deploy_v2.py" status "$backup"
strings devel/lib/mission_pkg/bt_ros > "$backup/binary_strings.txt"
if [[ "$mode" == candidate ]]; then
  grep -F '<MultimodalTargetTracker object_name' "$backup/binary_strings.txt"
  test -f devel/lib/multimodal_target_tracker.so
  /opt/conda/envs/demo/bin/python3 -m py_compile /home/ubuntu/model/mission_once.py
else
  grep -F '<TargetTracker object_name' "$backup/binary_strings.txt"
  ! grep -F '<MultimodalTargetTracker' "$backup/binary_strings.txt"
  test ! -e devel/lib/multimodal_target_tracker.so
fi
echo "VERIFIED_BUILD=$mode"
