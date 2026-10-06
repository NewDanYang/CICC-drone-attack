#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay real captured downward-camera frames through ArUco detector settings.

Synthetic markers did not reproduce the competition failure, so they cannot
validate a fix. This runs candidate detector configurations against actual
frames captured from /rflysim/sensor2/img_rgb during a mission, which is the
only honest way to tell whether a change helps.

It imports the real detector class from the deployed node so the replay uses
exactly the shipped code path, not a reimplementation.

Usage:
    python3 replay_aruco.py <frames_dir> [--truth-id 35]

Reports, per configuration: how many frames produce a correct ID, and the
first-frame latency (a proxy for how fast the mission would proceed).
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

NODE_PATH = "/home/ubuntu/catkin_ws/src/mission_pkg/scripts"


def load_gray(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def make_params(refine, win=5, iters=30, acc=0.1, adaptive=None):
    p = cv2.aruco.DetectorParameters_create()
    if refine:
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        p.cornerRefinementWinSize = win
        p.cornerRefinementMaxIterations = iters
        p.cornerRefinementMinAccuracy = acc
    if adaptive is not None:
        p.adaptiveThreshWinSizeMin = adaptive[0]
        p.adaptiveThreshWinSizeMax = adaptive[1]
        p.adaptiveThreshWinSizeStep = adaptive[2]
    return p


def detect(gray, aruco_dict, params, upscale, blur=None, clahe=False):
    g = gray
    if clahe:
        g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    if blur:
        g = cv2.GaussianBlur(g, (blur, blur), 0)
    if upscale and upscale != 1.0:
        g = cv2.resize(g, None, fx=upscale, fy=upscale,
                       interpolation=cv2.INTER_CUBIC)
    corners, ids, rejected = cv2.aruco.detectMarkers(g, aruco_dict, parameters=params)
    n_rej = 0 if rejected is None else len(rejected)
    if ids is None or len(ids) == 0:
        return None, n_rej
    return int(ids[0][0]), n_rej


CONFIGS = [
    ("baseline (shipped defaults)",      dict(refine=False, upscale=1.0)),
    ("current deployed (2x+subpix)",     dict(refine=True,  upscale=2.0)),
    ("3x + subpix",                      dict(refine=True,  upscale=3.0)),
    ("clahe + 2x + subpix",              dict(refine=True,  upscale=2.0, clahe=True)),
    ("clahe + 3x + subpix",              dict(refine=True,  upscale=3.0, clahe=True)),
    ("wide adaptive 5..31 step 5, 2x",   dict(refine=True,  upscale=2.0,
                                              adaptive=(5, 31, 5))),
    ("clahe+wide adapt+3x",              dict(refine=True,  upscale=3.0, clahe=True,
                                              adaptive=(5, 31, 5))),
    ("preblur3 + 3x + subpix",           dict(refine=True,  upscale=3.0, blur=3)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--truth-id", type=int, default=35)
    ap.add_argument("--dict-id", type=int, default=16)
    ap.add_argument("--measure", action="store_true",
                    help="report candidate/marker pixel sizes to size the problem")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.frames_dir, "*.png")))
    if not paths:
        sys.exit(f"no PNG frames in {a.frames_dir}")
    grays = [(os.path.basename(p), load_gray(p)) for p in paths]
    grays = [(n, g) for n, g in grays if g is not None]
    print(f"{len(grays)} frames from {a.frames_dir}, truth id={a.truth_id}\n")

    d = cv2.aruco.getPredefinedDictionary(a.dict_id)

    if a.measure:
        print("=== candidate / detected sizes (px) ===")
        for name, g in grays:
            p = make_params(True)
            corners, ids, rejected = cv2.aruco.detectMarkers(g, d, parameters=p)
            rej_sizes = []
            for r in (rejected or []):
                pts = r.reshape(-1, 2)
                w = float(np.linalg.norm(pts[1] - pts[0]))
                rej_sizes.append(round(w, 1))
            got = None
            if ids is not None and len(ids) > 0:
                pts = corners[0].reshape(-1, 2)
                got = (int(ids[0][0]),
                       round(float(np.linalg.norm(pts[1] - pts[0])), 1))
            print(f"  {name}: detected={got} rej_widths={rej_sizes[:6]}")
        print()

    print(f"{'config':34s} {'hits':>7s} {'first@':>7s} {'mean_rej':>9s}")
    print("-" * 62)
    for label, kw in CONFIGS:
        params = make_params(kw.get("refine", False),
                             adaptive=kw.get("adaptive"))
        hits = 0
        first = None
        rej_sum = 0
        for i, (name, g) in enumerate(grays):
            mid, n_rej = detect(g, d, params,
                                kw.get("upscale", 1.0),
                                blur=kw.get("blur"),
                                clahe=kw.get("clahe", False))
            rej_sum += n_rej
            if mid == a.truth_id:
                hits += 1
                if first is None:
                    first = i
        first_s = "-" if first is None else str(first)
        print(f"{label:34s} {hits:>7d} {first_s:>7s} {rej_sum/max(1,len(grays)):>9.2f}")

    print("\nframe size:", grays[0][1].shape)


if __name__ == "__main__":
    main()
