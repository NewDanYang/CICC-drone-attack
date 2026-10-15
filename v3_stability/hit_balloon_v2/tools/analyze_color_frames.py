#!/usr/bin/env python3
"""Measure color blobs in real /rflysim/sensor1 frames; never adjudicates hits."""
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np


def mask_for_color(hsv, color):
    h, s, v = cv2.split(hsv)
    saturated = (s >= 80) & (v >= 60)
    if color == "red":
        hue = (h <= 12) | (h >= 170)
        saturated &= s >= 100
    elif color == "purple":
        hue = (h >= 125) & (h <= 165)
    elif color == "blue":
        # The arena wall/sky is also blue (typically H~105,S~110). The
        # balloon measured from a real frame is H~120,S>200.
        hue = (h >= 112) & (h <= 130)
        saturated &= s >= 180
    else:
        raise ValueError(color)
    return (hue & saturated).astype(np.uint8)


def frame_measurement(path, color):
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"cannot read {path}")
    mask = mask_for_color(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV), color)
    count, _, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return int(mask.sum()), 0, "", ""
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (int(mask.sum()), int(stats[index, cv2.CC_STAT_AREA]),
            round(float(centers[index, 0]), 1), round(float(centers[index, 1]), 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument("color", choices=["red", "purple", "blue"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frames = args.trial_dir / "real_frames"
    with (frames / "frames.jsonl").open(encoding="utf-8") as source, args.output.open(
            "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=[
            "wall_time", "image", "color", "color_pixel_count",
            "largest_blob_pixels", "blob_cx", "blob_cy", "odom_x", "odom_y", "odom_z"])
        writer.writeheader()
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            pixels, largest, cx, cy = frame_measurement(frames / row["image"], args.color)
            odom = row.get("odom") or {}
            writer.writerow({
                "wall_time": row["wall_time"], "image": row["image"], "color": args.color,
                "color_pixel_count": pixels, "largest_blob_pixels": largest,
                "blob_cx": cx, "blob_cy": cy,
                "odom_x": odom.get("x", ""), "odom_y": odom.get("y", ""),
                "odom_z": odom.get("z", "")})


if __name__ == "__main__":
    main()
