"""Window search for FM9G yes/no localisation (pure numpy; no model, no ROS).

Why: on real frames FM9G4B-V's native <box> output was placeholder coordinates
("400 400 600 600", "500 500 600 600", repeated "500 500 500 500"; 2-10 s/call),
while its single-token yes/no answer is fast and sharp (5.0 study).  So the box
is found by asking FM9G, for many candidate windows at once, whether the window
tightly contains the target, coarse to fine.  Every decision is FM9G's.
"""
import numpy as np

W, H = 640, 480


def clamp_window(cx, cy, w, h, width=W, height=H):
    w, h = min(w, width), min(h, height)
    x1 = min(max(cx - w / 2.0, 0.0), width - w)
    y1 = min(max(cy - h / 2.0, 0.0), height - h)
    return (float(x1), float(y1), float(x1 + w), float(y1 + h))


def coarse_windows(sides, aspect=1.0, step_frac=0.5, width=W, height=H):
    """Grid of windows; `sides` are heights in px, width = aspect * height."""
    out = []
    for h in sides:
        w = aspect * h
        sx, sy = max(8.0, w * step_frac), max(8.0, h * step_frac)
        xs = np.arange(w / 2.0, width - w / 2.0 + 1e-6, sx) if w < width else [width / 2.0]
        ys = np.arange(h / 2.0, height - h / 2.0 + 1e-6, sy) if h < height else [height / 2.0]
        for cy in ys:
            for cx in xs:
                out.append(clamp_window(cx, cy, w, h, width, height))
    return sorted(set(out))


def refine_windows(box, shift=0.12, scales=(0.85, 1.0, 1.18), steps=(-1, 0, 1), width=W, height=H):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    out = set()
    for s in scales:
        for dy in steps:
            for dx in steps:
                out.add(clamp_window(cx + dx * shift * w, cy + dy * shift * h, w * s, h * s, width, height))
    return sorted(out)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def top_seeds(windows, scores, k=3, min_score=0.3, max_iou=0.3):
    """Best k windows that do not overlap each other much (greedy NMS)."""
    order = np.argsort(-np.asarray(scores))
    seeds = []
    for i in order:
        if scores[i] < min_score:
            break
        if all(iou(windows[i], windows[j]) <= max_iou for j in seeds):
            seeds.append(int(i))
        if len(seeds) >= k:
            break
    return seeds
