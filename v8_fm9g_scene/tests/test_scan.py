"""Window-search logic with a stand-in scorer (answers by overlap with a hidden box).
Tests the search, not FM9G accuracy (that is offline_eval on real frames)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
from fm9g_scene import scan as sc            # noqa: E402
from fm9g_scene.model_io import SceneModel    # noqa: E402
from fm9g_scene.targets import TARGETS        # noqa: E402


def make_model(truths, sharp=8.0):
    m = SceneModel(None, None, None, None, lambda **e: None, None)

    def score(bgr, windows, prompt, batch=64):
        out = []
        for w in windows:
            best = max(sc.iou(w, t) for t in truths) if truths else 0.0
            out.append(float(1 / (1 + np.exp(-sharp * (best - 0.55)))))
        return out
    m._score = score
    return m


def test_coarse_grid_covers_image_and_stays_inside():
    ws = sc.coarse_windows((96, 200, 280))
    assert all(0 <= w[0] and w[2] <= 640 and 0 <= w[1] and w[3] <= 480 for w in ws)
    assert 100 < len(ws) < 600


@pytest.mark.parametrize('truth', [[252, 172, 384, 304], [40, 200, 150, 310], [380, 60, 620, 300]])
def test_scan_finds_single_frame(truth):
    m = make_model([truth])
    boxes = m.scan_boxes(None, TARGETS['square_frame'], 'd')
    assert len(boxes) == 1 and sc.iou(boxes[0], truth) > 0.7


def test_scan_returns_nothing_when_absent():
    assert make_model([]).scan_boxes(None, TARGETS['square_frame'], 'd') == []


def test_scan_multi_finds_two_pillars():
    truths = [[100, 120, 170, 300], [430, 100, 520, 330]]
    boxes = make_model(truths).scan_boxes(None, TARGETS['pillar'], 'd')
    assert len(boxes) >= 2
    for t in truths:
        assert max(sc.iou(b, t) for b in boxes) > 0.55


def test_prior_remeasure_is_cheap_and_accurate():
    truth = [262, 176, 392, 306]
    m = make_model([truth])
    calls = []
    orig = m._score
    m._score = lambda bgr, w, p, batch=64: (calls.append(len(w)), orig(bgr, w, p))[1]
    boxes = m.scan_boxes(None, TARGETS['square_frame'], 'd', prior=[252, 172, 384, 304])
    assert sc.iou(boxes[0], truth) > 0.7
    assert sum(calls) < 120          # vs ~440 for a full search


def test_prior_falls_back_to_full_search_when_target_moved():
    truth = [40, 200, 150, 310]
    m = make_model([truth])
    boxes = m.scan_boxes(None, TARGETS['square_frame'], 'd', prior=[400, 100, 560, 260])
    assert sc.iou(boxes[0], truth) > 0.7
