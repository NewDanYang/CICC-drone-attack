#!/usr/bin/env bash
# Build only an existing, isolated RC1 overlay. Never edits the underlay.
set -Eeuo pipefail
WS="$(realpath "${TCEI_WS_ROOT:?set TCEI_WS_ROOT to the isolated workspace}")"
UNDERLAY="$(realpath "${TCEI_UNDERLAY_WS:-/home/ubuntu/catkin_ws}")"
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(realpath "$TOOLS/../../..")"
[[ "$WS" != "$UNDERLAY" && "$WS/" != "$UNDERLAY/"* ]] || {
  echo 'refusing to build in the preserved underlay' >&2; exit 2;
}
[[ -f "$UNDERLAY/devel/setup.bash" ]] || exit 2
/usr/bin/python3 "$TOOLS/materialize_stable_rc1_workspace.py" \
  --candidate-root "$ROOT" --workspace "$WS" --underlay "$UNDERLAY" --output "$WS/rc1-source-materialization.json"
/usr/bin/python3 "$TOOLS/prepare_sequential_deployment.py" \
  --expected-manifest "$TOOLS/../deploy/sequential_release_manifest.json" \
  --stage-plugin-package "$WS/src/mission_pkg" > "$WS/rc1-preparation.json"
# Preserve the exact repository model identity; do not train or substitute weights.
/usr/bin/python3 - "$WS" "$UNDERLAY" <<'PYMODEL'
import hashlib, shutil, sys
from pathlib import Path
ws, underlay = map(Path, sys.argv[1:])
model = ws / 'src/object_det/models/best.pt'
if not model.is_file():
    source = underlay / 'src/object_det/models/best.pt'
    data = source.read_bytes()
    expected = '57cc0e64990b5a34e22a31067dd807f8e08d3274'
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == expected, 'underlay model differs from main'
    model.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, model)
assert hashlib.sha1(b'blob ' + str(model.stat().st_size).encode() + b'\0' + model.read_bytes()).hexdigest() == '57cc0e64990b5a34e22a31067dd807f8e08d3274'
(ws / 'rc1-detector-model.sha256').write_text(hashlib.sha256(model.read_bytes()).hexdigest() + '  ' + str(model) + '\n')
PYMODEL
# The legacy package recursively builds research decorators. Exclude these
# before CMake generates targets, and quarantine any previous plugin output.
/usr/bin/python3 - "$WS" <<'PY'
import hashlib
from pathlib import Path
import sys
ws = Path(sys.argv[1])
path = ws / 'src/mission_pkg/CMakeLists.txt'
old = path.read_bytes()
anchor = b'foreach(SOURCE_FILE ${SOURCE_FILES})'
guard = b'\n    # Exclude research vision from Stable RC1.\n    if(SOURCE_FILE MATCHES "fm9g_balloon_stage[.]cpp$|multimodal.*[.]cpp$")\n        continue()\n    endif()\n'
if guard not in old:
    if old.count(anchor) != 1:
        raise SystemExit('unknown plugin scan; review CMake before proceeding')
    backup = path.with_name('CMakeLists.txt.bak_' + hashlib.sha256(old).hexdigest()[:12])
    if not backup.exists():
        backup.write_bytes(old)
    path.write_bytes(old.replace(anchor, anchor + guard))
for pattern in ('fm9g_balloon_stage.so', '*multimodal*.so'):
    for lib in (ws / 'devel/lib').glob(pattern):
        quarantine = ws / 'quarantine'
        quarantine.mkdir(exist_ok=True)
        target = quarantine / (lib.name + '.' + hashlib.sha256(lib.read_bytes()).hexdigest()[:12])
        if target.exists():
            raise SystemExit('quarantine target exists; inspect before moving ' + str(lib))
        lib.rename(target)
PY
set +u
source /opt/ros/noetic/setup.bash
source "$UNDERLAY/devel/setup.bash"
set -u
cd "$WS"
catkin_make --force-cmake --pkg mission_pkg -j2 \
  -DPYTHON_EXECUTABLE=/usr/bin/python3 \
  "-DCMAKE_SHARED_LINKER_FLAGS=-L$UNDERLAY/devel/lib" \
  "-DCMAKE_EXE_LINKER_FLAGS=-L$UNDERLAY/devel/lib"
set +u
source "$WS/devel/setup.bash"
set -u
[[ "$(rospack find mission_pkg)" == "$WS/src/mission_pkg" ]] || exit 2
[[ "$(rospack find object_det)" == "$WS/src/object_det" ]] || exit 2
"$WS/devel/lib/mission_pkg/bt_ros" --check-plugins
sha256sum "$WS/devel/lib/mission_pkg/bt_ros" "$WS"/devel/lib/*.so > "$WS/rc1-built-artifacts.sha256"
