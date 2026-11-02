#!/usr/bin/env bash
# Undo deploy.sh:   bash rollback.sh <backup_dir>
# Quick runtime-only rollback without rebuilding (BT templates only):
#   rosparam set /fm9g_scene/enabled false     # next mission uses the exact official XML
set -euo pipefail
BACKUP="${1:?backup directory}"
MODEL=${FM9G_MODEL_DIR:-/home/ubuntu/model}
WS=${FM9G_WS:-/home/ubuntu/catkin_ws}
PKG=$WS/src/mission_pkg
YAML=$WS/src/object_det/config/detection_params.yaml
if [[ -e /tmp/tcei_formal_trial.lock ]]; then
  echo "formal trial lock present; refusing to roll back during a trial" >&2; exit 3
fi
cp -p "$BACKUP/mission_once.py" "$MODEL/mission_once.py"
cp -p "$BACKUP/bt_ros.cpp" "$PKG/src/bt_ros.cpp"
cp -p "$BACKUP/detection_params.yaml" "$YAML"
rm -f "$PKG/src/nodes/perception/fm9g_locate.cpp" "$WS/devel/lib/fm9g_locate.so"
if [[ -d "$MODEL/fm9g_scene" ]]; then mv "$MODEL/fm9g_scene" "$BACKUP/fm9g_scene.removed_$(date +%s)"; fi
set +u; source ${FM9G_ROS_SETUP:-/opt/ros/noetic/setup.bash}; source "$WS/devel/setup.bash"; set -u
( cd "$WS" && catkin_make --force-cmake --pkg mission_pkg -j2 ) > "$BACKUP/rollback_build.log" 2>&1
if strings "$WS/devel/lib/mission_pkg/bt_ros" | grep -qF 'Fm9gLocate'; then
  echo "rebuilt bt_ros still contains Fm9gLocate templates; see $BACKUP/rollback_build.log" >&2; exit 6
fi
md5sum -c "$BACKUP/before.md5"
echo "ROLLED_BACK (full environment restart required so the detector reloads its YAML)"
