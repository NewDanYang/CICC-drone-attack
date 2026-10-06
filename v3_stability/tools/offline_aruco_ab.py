#!/usr/bin/env python3
"""Offline A/B of ArUco detection params at the real in-sim marker scale.

Reproduces the geometry of the competition: 0.15 m marker, 640x480 frame,
90 deg FOV, viewed from the hover altitude, then compares detection with the
shipped defaults vs the upscale+subpixel-refine settings.
"""
import cv2
import numpy as np

DICT_ID = 16          # DICT_ARUCO_ORIGINAL, as configured in aruco_detect.launch
MARKER_ID = 35
MARKER_M = 0.15
FRAME_W, FRAME_H = 640, 480
FOV_DEG = 90.0


def px_per_meter(alt_m):
    """Ground sampling distance for a nadir camera: footprint width at that
    altitude, divided across the frame width."""
    footprint_m = 2.0 * alt_m * np.tan(np.radians(FOV_DEG / 2.0))
    return FRAME_W / footprint_m


def render(alt_m, blur_px, jpeg_q=90, rotate_deg=0.0):
    """Build a realistic frame: marker at the right pixel scale, blurred by
    motion, then JPEG-compressed (the sim ships RGB but this matches the kind
    of softness seen in the real captures)."""
    ppm = px_per_meter(alt_m)
    side = int(round(MARKER_M * ppm))
    d = cv2.aruco.getPredefinedDictionary(DICT_ID)
    marker = cv2.aruco.drawMarker(d, MARKER_ID, side)

    frame = np.full((FRAME_H, FRAME_W), 200, dtype=np.uint8)
    frame[:] = 200
    y0 = (FRAME_H - side) // 2
    x0 = (FRAME_W - side) // 2
    frame[y0:y0 + side, x0:x0 + side] = marker

    if rotate_deg:
        m = cv2.getRotationMatrix2D((FRAME_W / 2, FRAME_H / 2), rotate_deg, 1.0)
        frame = cv2.warpAffine(frame, m, (FRAME_W, FRAME_H),
                               borderValue=200)
    if blur_px > 0:
        k = int(blur_px) | 1
        frame = cv2.GaussianBlur(frame, (k, k), 0)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_q])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE), side


def params_old():
    p = cv2.aruco.DetectorParameters_create()
    return p


def params_new(upscale):
    p = cv2.aruco.DetectorParameters_create()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 5
    p.cornerRefinementMaxIterations = 30
    p.cornerRefinementMinAccuracy = 0.1
    return p


def try_detect(gray, params, upscale):
    if upscale != 1.0:
        g = cv2.resize(gray, None, fx=upscale, fy=upscale,
                       interpolation=cv2.INTER_CUBIC)
    else:
        g = gray
    d = cv2.aruco.getPredefinedDictionary(DICT_ID)
    corners, ids, rejected = cv2.aruco.detectMarkers(g, d, parameters=params)
    hit = ids is not None and len(ids) > 0 and int(ids[0][0]) == MARKER_ID
    return hit, (0 if ids is None else len(ids)), (0 if rejected is None else len(rejected))


def main():
    print(f"{'alt':>5} {'px':>4} {'blur':>5} {'rot':>5} | {'old':>5} | {'new':>5}")
    print("-" * 44)
    old_ok = new_ok = total = 0
    for alt in (1.0, 1.2, 1.4):
        for blur in (0, 1, 3, 5):
            for rot in (0.0, 8.0):
                gray, side = render(alt, blur, rotate_deg=rot)
                ho, _, _ = try_detect(gray, params_old(), 1.0)
                hn, _, _ = try_detect(gray, params_new(2.0), 2.0)
                total += 1
                old_ok += ho
                new_ok += hn
                mark = "" if ho == hn else ("  <-- fixed" if hn else "  <-- regression")
                print(f"{alt:>5.2f} {side:>4} {blur:>5} {rot:>5.0f} | "
                      f"{'HIT' if ho else '.':>5} | {'HIT' if hn else '.':>5}{mark}")
    print("-" * 44)
    print(f"defaults  : {old_ok}/{total}")
    print(f"upscale2x : {new_ok}/{total}")


if __name__ == "__main__":
    main()
