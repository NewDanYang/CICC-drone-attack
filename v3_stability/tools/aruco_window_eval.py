#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare ArUco detector configurations on REAL captured frames.

This is the tool that produced the numbers in v3_stability/README.md, and the
one to use for any new claim. Captured frames come from
`capture_mission_frames.sh`, which records /rflysim/sensor2/img_rgb during a
real trial.

Why a window-restricted score matters: the mission only enables detection for a
~20 s window at the hover point, during which the marker is in view. Scoring
over all frames mixes in the long stretches where the marker is simply not
visible, which dilutes the difference between configurations. Pass --lo/--hi
(the frame indices spanning ENABLED..DISABLED, derived from the trial's
telemetry) to score the window that actually decides the mission.

Usage:
    python3 aruco_window_eval.py <frames_dir> [--lo 62] [--hi 82]
                                [--truth-id 35] [--dict-id 16]
"""
import argparse
import glob
import os
import sys

import cv2

DEFAULT_CONFIGS = [
    ("official default (1x, no refine)", False, 1.0, False),
    ("2x + subpix (known regression)",   True,  2.0, False),
    ("clahe only (1x, no refine)",       False, 1.0, True),
    ("clahe + 3x + subpix (proposed)",   True,  3.0, True),
    ("3x + subpix (no clahe)",           True,  3.0, False),
    ("clahe + 3x (no subpix)",           False, 3.0, True),
]


def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def make_params(refine):
    p = cv2.aruco.DetectorParameters_create()
    if refine:
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        p.cornerRefinementWinSize = 5
        p.cornerRefinementMaxIterations = 30
        p.cornerRefinementMinAccuracy = 0.1
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--lo", type=int, default=None,
                    help="first frame index of the ArUco window")
    ap.add_argument("--hi", type=int, default=None,
                    help="last frame index of the ArUco window")
    ap.add_argument("--truth-id", type=int, default=35)
    ap.add_argument("--dict-id", type=int, default=16)
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.frames_dir, "*.png")))
    if not paths:
        sys.exit(f"no PNG frames in {a.frames_dir}")
    frames = []
    for p in paths:
        g = load_gray(p)
        if g is not None:
            frames.append((os.path.basename(p), g))
    if not frames:
        sys.exit("no readable frames")

    lo = a.lo if a.lo is not None else 0
    hi = a.hi if a.hi is not None else len(frames) - 1
    hi = min(hi, len(frames) - 1)

    print(f"frames={len(frames)}  window={lo}..{hi} ({hi - lo + 1} frames)  "
          f"truth_id={a.truth_id}")
    print(f"frame size = {frames[0][1].shape}")
    if a.lo is None:
        print("NOTE: no --lo/--hi given; scoring all frames. Pass the ENABLED.."
              "DISABLED indices for the mission-relevant number.")
    print()

    d = cv2.aruco.getPredefinedDictionary(a.dict_id)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    print(f"{'config':36s} {'window':>10s} {'all':>7s}")
    print("-" * 56)
    for label, refine, up, use_clahe in DEFAULT_CONFIGS:
        pm = make_params(refine)
        win_hits = all_hits = 0
        for i, (name, g) in enumerate(frames):
            gg = clahe.apply(g) if use_clahe else g
            if up != 1.0:
                gg = cv2.resize(gg, None, fx=up, fy=up,
                                interpolation=cv2.INTER_CUBIC)
            _, ids, _ = cv2.aruco.detectMarkers(gg, d, parameters=pm)
            if ids is not None and len(ids) > 0 and int(ids[0][0]) == a.truth_id:
                all_hits += 1
                if lo <= i <= hi:
                    win_hits += 1
        print(f"{label:36s} {win_hits:>5d}/{hi - lo + 1:<4d} {all_hits:>7d}")


if __name__ == "__main__":
    main()
