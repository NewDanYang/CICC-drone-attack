#!/usr/bin/env bash
# One-shot, NO-FLIGHT checks of v8 on the simulation server.  Changes nothing
# in /home/ubuntu (no deploy, no ROS, no simulator).  Needs the GPU free.
#
#   cd <unzipped>/v8_fm9g_scene && bash tools/server_check.sh
#
# Steps:
#   1 unit tests (geometry + wiring)
#   2 patch dry-run against the LIVE mission_once.py / bt_ros.cpp (writes only to OUT)
#   3 command generation check: original vs greedy (model loaded twice, ~2-4 min)
#   4 FM9G square_frame / pillar recognition on the real 6.3 frame-audit images,
#     with the old presence-sweep locator as A/B and YOLO as offline reference
# Result: $OUT.tar.gz -> send it back.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=${FM9G_CONDA_PY:-/opt/conda/envs/demo/bin/python3}
MODEL=/home/ubuntu/model
WS=/home/ubuntu/catkin_ws
TS=$(date +%Y%m%dT%H%M%S)
OUT=${OUT:-/root/gpufree-data/fm9g_v8/server_check_$TS}
mkdir -p "$OUT"
set +u; source /opt/ros/noetic/setup.bash; source "$WS/devel/setup.bash"; set -u   # rospy for mission_once import
exec > >(tee "$OUT/console.log") 2>&1
echo "v8 server check $TS -> $OUT"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv | tee "$OUT/gpu.txt"
if pgrep -f "[m]ission_once.py" >/dev/null; then
  echo "WARNING: a mission_once.py process is running (it holds the GPU model). Stop it first."; exit 3
fi
if [[ -e /tmp/tcei_formal_trial.lock ]]; then echo "formal trial lock present; aborting"; exit 3; fi
md5sum "$MODEL/mission_once.py" "$WS/src/mission_pkg/src/bt_ros.cpp" \
       "$WS/src/object_det/config/detection_params.yaml" | tee "$OUT/live.md5"

echo "== 1 unit tests"
"$PY" -m pip show pytest >/dev/null 2>&1 || "$PY" -m pip install -q pytest
( cd "$HERE/.." && "$PY" -m pytest v8_fm9g_scene/tests -q -p no:cacheprovider ) | tee "$OUT/tests.txt"
[[ ${PIPESTATUS[0]} -eq 0 ]] || { echo "GATE1_STOP unit tests failed"; tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"; exit 4; }

echo "== 2 patch dry-run on live files"
python3 "$HERE/patches/patch_mission_once.py" "$MODEL/mission_once.py" "$OUT/mission_once.v8.py" 2>&1 | tee "$OUT/patch_mission.txt"
python3 "$HERE/patches/patch_bt_ros.py" "$WS/src/mission_pkg/src/bt_ros.cpp" "$OUT/bt_ros.v8.cpp" 2>&1 | tee "$OUT/patch_bt.txt"
if [[ ! -s "$OUT/mission_once.v8.py" || ! -s "$OUT/bt_ros.v8.cpp" ]]; then
  echo "GATE1_STOP patch dry-run failed"; tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"; exit 4
fi
"$PY" -m py_compile "$OUT/mission_once.v8.py" || { echo "GATE1_STOP patched mission does not compile"; exit 4; }

echo "== 3 command generation: original (sampling) vs v8 (greedy)"
cp "$MODEL/mission_once.py" "$MODEL/.mission_once_orig_check_$TS.py"
cp "$OUT/mission_once.v8.py" "$MODEL/.mission_once_v8_check_$TS.py" 2>/dev/null
( cd "$MODEL" && timeout 600 "$PY" "$HERE/tools/command_check.py" --mission "$MODEL/.mission_once_orig_check_$TS.py" \
    --repeats 2 --out "$OUT/command_original.json" ) 2>&1 | tail -15
if [[ -f "$MODEL/.mission_once_v8_check_$TS.py" ]]; then
  ( cd "$MODEL" && timeout 600 "$PY" "$HERE/tools/command_check.py" --mission "$MODEL/.mission_once_v8_check_$TS.py" \
      --repeats 2 --out "$OUT/command_greedy.json" ) 2>&1 | tail -15
fi
rm -f "$MODEL/.mission_once_orig_check_$TS.py" "$MODEL/.mission_once_v8_check_$TS.py"
if ! python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d['passed']>=9 else 1)" "$OUT/command_greedy.json" 2>/dev/null; then
  echo "GATE1_STOP greedy command check missing or < 9/10"; tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"; exit 4
fi

echo "== 4 FM9G recognition on real 6.3 frames"
IMGS=${IMGS:-$(ls -d /home/ubuntu/tcei_baseline_tools/results/multimodal_frame_v1/*/images /root/gpufree-data/square-frame-flight/*/images /root/gpufree-data/square-frame-flight/*/*/images 2>/dev/null | tail -1)}
if [[ -n "$IMGS" && -d "$IMGS" ]]; then
  echo "images: $IMGS ($(ls "$IMGS" | wc -l) files)"
  ( cd "$MODEL" && "$PY" "$HERE/tools/offline_eval.py" --images "$IMGS" --out "$OUT/eval_images" \
      --model-dir "$MODEL/FM9G4B-V" --workspace "$WS" --legacy-sweep --simulate-balloon-processor \
      --max-per-camera 60 ) 2>&1 | tail -60
else
  echo "no 6.3 frame images found; set IMGS=/path/to/images and re-run"
fi

tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
python3 - "$OUT" <<'PYEOF'
import json, sys, pathlib
o = pathlib.Path(sys.argv[1]); res = {}
for k in ('command_original', 'command_greedy'):
    f = o / (k + '.json')
    res[k] = (json.loads(f.read_text())['passed'], json.loads(f.read_text())['total']) if f.exists() else 'missing'
s = o / 'eval_images' / 'summary.json'
res['eval_images'] = 'present' if s.exists() else 'missing'
print('GATE1_SUMMARY', json.dumps(res))
PYEOF
echo "DONE -> $OUT.tar.gz  ($(du -h "$OUT.tar.gz" | cut -f1))"
