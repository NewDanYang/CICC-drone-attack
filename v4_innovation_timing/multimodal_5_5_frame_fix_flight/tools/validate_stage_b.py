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
assert 'COLOR_TEXT[color]' in runtime
assert '{COLOR_TEXT[color]}的气球' in runtime
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
    import numpy as np
    ns = {}
    exec(compile(ast.parse(presence), str(ROOT/'v2/presence.py'), 'exec'), ns)
    sweep_cls = ns['NativePresenceSweep']
    edge_box = sweep_cls.edge_box
    profile = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.2, 0.1, 0.1]
    box, p0, curves = edge_box([0.9] + profile[1:] * 4,
        [20.0, 40.0, 60.0, 80.0, 100.0, 120.0, 140.0, 160.0],
        (100, 80, 300, 280), (0.4, 0.5, 0.5, 0.4))
    assert p0 == 0.9 and len(curves) == 4 and box is not None
    # Regression: track interpolation must include the unmasked origin at
    # x=0.0.  A crossing in the final sample interval exercises both the
    # origin offset and the former positions[j] IndexError.
    xs = [0.0] + [20.0, 40.0, 60.0, 80.0]
    profile = [1.0, 1.0, 1.0, 1.0, 0.0]
    threshold = 0.5
    j = 4
    fraction = (profile[j - 1] - threshold) / (profile[j - 1] - profile[j])
    assert xs[j - 1] + fraction * (xs[j] - xs[j - 1]) == 70.0
    class FakeSweep:
        square = staticmethod(sweep_cls.square)
        edge_box = staticmethod(sweep_cls.edge_box)
        window_factor = 2.0
        n_track = 4
        thresholds = (0.4, 0.5, 0.5, 0.4)

        def sweep_imgs(self, frame, window, count):
            return None, [20.0, 40.0, 60.0, 80.0]

        def call(self, *args):
            # The right-side curve crosses in its final interval.  The old
            # implementation indexed positions[4] and raised IndexError.
            profiles = ([0.9, 0.1, 0.1, 0.1, 0.1],
                        [0.9, 0.9, 0.9, 0.9, 0.1],
                        [0.9, 0.9, 0.1, 0.1, 0.1],
                        [0.9, 0.9, 0.9, 0.1, 0.1])
            return [0.9] + [value for profile in profiles for value in profile[1:]]

        def audit(self, **kwargs):
            pass

    fake = FakeSweep()
    track_box = sweep_cls.track(fake, np.zeros((480, 640, 3), dtype=np.uint8),
                                '这张图片里有没有蓝色的气球？只回答“是”或“否”。',
                                [100.0, 100.0, 140.0, 140.0], 0, 'd', 's',
                                'blue', 1, 0.0)
    assert track_box is not None
    geometry_test = 'passed'
    track_interpolation_test = 'passed'
manifest = json.loads((ROOT/'v2/manifest.json').read_text())
assert 'v2/presence.py' in manifest['package_md5']
print(json.dumps({'runtime_forbidden_tokens': [], 'geometry_test': geometry_test,
                  'track_interpolation_test': locals().get('track_interpolation_test', 'skipped_without_torch'),
                  'edge_box': box,
                  'manifest_files': len(manifest['package_md5'])}, indent=2))
