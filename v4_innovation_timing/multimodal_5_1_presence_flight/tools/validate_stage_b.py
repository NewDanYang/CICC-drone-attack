#!/usr/bin/env python3
"""Offline source and geometry checks for the P12e stage-B package."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runtime = (ROOT/'v2/runtime.py').read_text(encoding='utf-8')
presence = (ROOT/'v2/presence.py').read_text(encoding='utf-8')

for forbidden in ('OverlapLocalizer', 'semantic_labels', 'local_regions', 'hsv_box', 'yolo'):
    assert forbidden.lower() not in runtime.lower(), forbidden
assert 'NativePresenceSweep' in runtime
assert 'presence_model_call' in presence
assert 'scan_curves' not in presence  # curves are recorded as `curves` in presence_sweep events
ast.parse(runtime)
ast.parse(presence)

geometry_test = 'skipped_without_torch'
try:
    import torch  # noqa: F401
except ModuleNotFoundError:
    box = None
else:
    ns = {}
    exec(compile(ast.parse(presence), str(ROOT/'v2/presence.py'), 'exec'), ns)
    edge_box = ns['NativePresenceSweep'].edge_box
    profile = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.2, 0.1, 0.1]
    box, p0, curves = edge_box([0.9] + profile[1:] * 4,
        [20.0, 40.0, 60.0, 80.0, 100.0, 120.0, 140.0, 160.0],
        (100, 80, 300, 280), (0.4, 0.5, 0.5, 0.4))
    assert p0 == 0.9 and len(curves) == 4 and box is not None
    geometry_test = 'passed'
manifest = json.loads((ROOT/'v2/manifest.json').read_text())
assert 'v2/presence.py' in manifest['package_md5']
print(json.dumps({'runtime_forbidden_tokens': [], 'geometry_test': geometry_test,
                  'edge_box': box,
                  'manifest_files': len(manifest['package_md5'])}, indent=2))
