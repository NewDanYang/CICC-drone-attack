#!/usr/bin/env bash
# Deploy the FM9G v8 scene perception candidate onto the simulation server.
#
#   bash deploy.sh <backup_dir>          # e.g. /root/gpufree-data/fm9g_v8/backup_$(date +%Y%m%dT%H%M%S)
#
# Changes (all backed up with MD5 first; rollback.sh <backup_dir> undoes them):
#   /home/ubuntu/model/mission_once.py                 greedy decoding + scene bridge entry
#   /home/ubuntu/model/fm9g_scene/                     new package (copied)
#   mission_pkg/src/bt_ros.cpp                         Fm9gLocate templates (param fm9g_scene/enabled)
#   mission_pkg/src/nodes/perception/fm9g_locate.cpp   new BT node (auto-globbed plugin)
#   object_det/config/detection_params.yaml            YOLO stops publishing square_frame
# Requires a FULL environment restart afterwards (the running detector keeps its old YAML).
set -euo pipefail
BACKUP="${1:?backup directory}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V8="$(cd "$HERE/.." && pwd)"
MODEL=${FM9G_MODEL_DIR:-/home/ubuntu/model}
WS=${FM9G_WS:-/home/ubuntu/catkin_ws}
PKG=$WS/src/mission_pkg
YAML=$WS/src/object_det/config/detection_params.yaml
CONDA_PY=${FM9G_CONDA_PY:-/opt/conda/envs/demo/bin/python3}

if [[ -e /tmp/tcei_formal_trial.lock ]]; then
  echo "formal trial lock present; refusing to deploy during a trial" >&2; exit 3
fi
if [[ -e "$BACKUP" ]]; then echo "backup dir exists: $BACKUP" >&2; exit 2; fi
mkdir -p "$BACKUP"

# ---- 1. backup + hashes ---------------------------------------------------
cp -p "$MODEL/mission_once.py" "$BACKUP/mission_once.py"
cp -p "$PKG/src/bt_ros.cpp" "$BACKUP/bt_ros.cpp"
cp -p "$YAML" "$BACKUP/detection_params.yaml"
[[ -e "$MODEL/fm9g_scene" ]] && { echo "$MODEL/fm9g_scene already exists" >&2; exit 4; }
[[ -e "$PKG/src/nodes/perception/fm9g_locate.cpp" ]] && { echo "fm9g_locate.cpp already exists" >&2; exit 4; }
md5sum "$MODEL/mission_once.py" "$PKG/src/bt_ros.cpp" "$YAML" > "$BACKUP/before.md5"
PROTECTED="launch/llm_mission.launch include/base/drone_action_node.h src/nodes/action/visual_servo.cpp include/nodes/action/visual_servo.h"
( cd "$PKG" && md5sum $PROTECTED ) > "$BACKUP/protected_before.md5"

# ---- 2. patched sources into staging (patchers refuse on anchor/MD5 mismatch)
STAGE="$BACKUP/candidate"; mkdir -p "$STAGE"
python3 "$V8/patches/patch_mission_once.py" "$MODEL/mission_once.py" "$STAGE/mission_once.py"
python3 "$V8/patches/patch_bt_ros.py" "$PKG/src/bt_ros.cpp" "$STAGE/bt_ros.cpp"
python3 - "$YAML" "$STAGE/detection_params.yaml" <<'EOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
b = open(src, 'rb').read()
old = b'target_classes: ["square_frame", "red_balloon"]'
if b.count(old) != 1:
    raise SystemExit('YAML anchor not found exactly once')
open(dst, 'xb').write(b.replace(old, b'target_classes: ["red_balloon"]'))
EOF

# ---- 3. install ------------------------------------------------------------
cp "$STAGE/mission_once.py" "$MODEL/mission_once.py"
cp -r "$V8/code/fm9g_scene" "$MODEL/fm9g_scene"
find "$MODEL/fm9g_scene" -name '__pycache__' -prune -exec rm -rf {} +
cp "$STAGE/bt_ros.cpp" "$PKG/src/bt_ros.cpp"
cp "$V8/cpp/fm9g_locate.cpp" "$PKG/src/nodes/perception/fm9g_locate.cpp"
cp "$STAGE/detection_params.yaml" "$YAML"
md5sum "$MODEL/mission_once.py" "$PKG/src/bt_ros.cpp" "$YAML" "$PKG/src/nodes/perception/fm9g_locate.cpp" \
  $(find "$MODEL/fm9g_scene" -name '*.py' | sort) > "$BACKUP/after.md5"

# ---- 4. build + verify ------------------------------------------------------
set +u; source ${FM9G_ROS_SETUP:-/opt/ros/noetic/setup.bash}; source "$WS/devel/setup.bash"; set -u
# --force-cmake: the node plugin list is a configure-time file(GLOB); a new .cpp is
# invisible to an incremental build.
( cd "$WS" && catkin_make --force-cmake --pkg mission_pkg -j2 ) > "$BACKUP/build.log" 2>&1 || {
  echo "BUILD FAILED, see $BACKUP/build.log; run rollback.sh $BACKUP" >&2; exit 5; }
test -f "$WS/devel/lib/fm9g_locate.so"
strings "$WS/devel/lib/mission_pkg/bt_ros" | grep -F 'Fm9gLocate object_name' > /dev/null
"$CONDA_PY" -m py_compile "$MODEL/mission_once.py"
( cd "$MODEL" && "$CONDA_PY" -c "import fm9g_scene.bridge, fm9g_scene.presence; print('import ok')" )
( cd "$PKG" && md5sum -c "$BACKUP/protected_before.md5" )
echo "VERIFIED_DEPLOY backup=$BACKUP"
echo "Next: FULL environment restart, then tools/command_check.py, then a capture + offline_eval before any flight."
