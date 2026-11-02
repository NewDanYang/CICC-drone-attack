"""Regenerate the v2 package manifest from the files actually on disk (v6)."""
import hashlib, json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = ['v2/localizer.py', 'v2/tracking.py', 'v2/runtime.py', 'v2/refinement.py',
         'v2/geometry.py', 'v2/presence.py', 'v2/v5_guard.py', 'v2/v6_estimator.py',
         'v2/multimodal_target_tracker.h', 'v2/multimodal_target_tracker.cpp',
         'v2/entry_main.py.txt', 'v2/mission_once.py', 'v2/bt_ros.cpp']
out = {}
for name in files:
    path = root / name
    if path.exists():
        out[name] = hashlib.md5(path.read_bytes()).hexdigest()
(root / 'v2/manifest.json').write_text(json.dumps({'package_md5': out}, indent=2), encoding='utf-8')
print(json.dumps(out, indent=2))
