"""Geometry tests.  Run: python3 -m pytest v8_fm9g_scene/tests -q"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
from fm9g_scene import geometry as g  # noqa: E402

OBSERVE = np.array([0.0, -1.0, 1.0])          # cross_frame/observe_pos
FRAME = np.array([3.25, -0.4, 1.0])           # cross_frame/expected_pos
FRAME_SIZE = 1.3


def world_to_front_pixel(p_w, pos, R_wb):
    p_body = R_wb.T @ (np.asarray(p_w) - pos)
    p_cam = g.FRONT_CAM_R.T @ (p_body - g.FRONT_CAM_T)
    fx, fy, cx, cy = g.FRONT_INTRINSICS
    return cx + fx * p_cam[0] / p_cam[2], cy + fy * p_cam[1] / p_cam[2], p_cam[2]


def frame_box_at(pos, yaw=0.0):
    R = g.quat_to_R(*g.yaw_quat(yaw))
    corners = [FRAME + np.array([0, dy, dz]) for dy in (-0.65, 0.65) for dz in (-0.65, 0.65)]
    px = [world_to_front_pixel(c, pos, R) for c in corners]
    us, vs = [p[0] for p in px], [p[1] for p in px]
    return [min(us), min(vs), max(us), max(vs)], R


def synthetic_frame_cloud(pos, R_wb, step=2, bar=0.1):
    """Ray-cast a pixel grid like a depth camera: frame bars (0.1 m wide,
    outer 1.3 m) in the plane x=3.25, a far wall at x=6 everywhere else."""
    fx, fy, cx, cy = g.FRONT_INTRINSICS
    pts = []
    origin = pos + R_wb @ g.FRONT_CAM_T
    for v in range(0, 480, step):
        for u in range(0, 640, step):
            ray = R_wb @ (g.FRONT_CAM_R @ np.array([(u - cx) / fx, (v - cy) / fy, 1.0]))
            t = (FRAME[0] - origin[0]) / ray[0]
            hit = origin + t * ray
            dy, dz = hit[1] - FRAME[1], hit[2] - FRAME[2]
            on_bar = (max(abs(dy), abs(dz)) <= 0.65 and
                      max(abs(dy), abs(dz)) >= 0.65 - bar)
            if not on_bar:
                hit = origin + ((6.0 - origin[0]) / ray[0]) * ray
            pts.append(hit)
    pts = np.array(pts)
    body = (pts - pos) @ R_wb          # world -> body
    return body - g.DEPTH_SENSOR_T     # body -> depth sensor


def test_quat_identity_and_yaw():
    assert np.allclose(g.quat_to_R(0, 0, 0, 1), np.eye(3))
    R = g.quat_to_R(*g.yaw_quat(math.pi / 2))
    assert np.allclose(R @ [1, 0, 0], [0, 1, 0], atol=1e-9)


def test_native_box_scaling():
    assert g.native_to_pixels([0, 0, 1000, 1000]) == [0, 0, 640, 480]
    with pytest.raises(ValueError):
        g.native_to_pixels([500, 0, 400, 100])


def test_true_frame_box_size_and_world_roundtrip():
    box, R = frame_box_at(OBSERVE)
    w = box[2] - box[0]
    # 1.3 m at ~3.15 m optical depth with fx=320 -> ~132 px
    assert 125 < w < 140
    d_w, d_h = g.size_depth(box, FRAME_SIZE, FRAME_SIZE)
    assert abs(d_w - 3.15) < 0.05 and abs(d_h - 3.15) < 0.05
    cu, cv = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    p = g.front_pixel_to_world(cu, cv, d_w, OBSERVE, R)
    assert np.allclose(p, FRAME, atol=0.05)


def test_report_failure_is_reproduced_by_an_oversized_box():
    """Report: rejected estimates x~1.81-1.85.  A ~1.8x too-large box gives that."""
    box, R = frame_box_at(OBSERVE)
    cu, cv = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    big = 1.8 * (box[2] - box[0])
    fake = [cu - big / 2, cv - big / 2, cu + big / 2, cv + big / 2]
    d, _ = g.size_depth(fake, FRAME_SIZE, FRAME_SIZE)
    p = g.front_pixel_to_world(cu, cv, d, OBSERVE, R)
    assert 1.7 < p[0] < 1.95
    # xy distance from expected_pos exceeds TargetLocator's 1.0 m tolerance
    assert np.linalg.norm(p[:2] - FRAME[:2]) > 1.0
    # and the depth camera would have flagged it
    u, v, z = g.project_depth_points(synthetic_frame_cloud(OBSERVE, R))
    d_cloud, _ = g.box_depth(u, v, z, fake, mode='hollow')
    assert not g.depth_consistent(d_cloud, d)


def test_hollow_ring_depth_ignores_far_wall():
    box, R = frame_box_at(OBSERVE)
    u, v, z = g.project_depth_points(synthetic_frame_cloud(OBSERVE, R))
    d_ring, n = g.box_depth(u, v, z, box, mode='hollow')
    assert n > 100
    assert abs(d_ring - 3.15) < 0.1
    # naive median over the whole box would be pulled toward the wall
    inside = (u >= box[0]) & (u <= box[2]) & (v >= box[1]) & (v <= box[3])
    assert np.median(z[inside]) > d_ring + 0.5
    d_size, _ = g.size_depth(box, FRAME_SIZE, FRAME_SIZE)
    assert g.depth_consistent(d_ring, d_size)


def test_depth_projection_matches_rgb_projection():
    pos, R = OBSERVE, np.eye(3)
    target = np.array([2.0, -1.3, 1.4])
    u0, v0, z0 = world_to_front_pixel(target, pos, R)
    sensor = (target - pos) - g.DEPTH_SENSOR_T
    u, v, z = g.project_depth_points(sensor[None])
    assert abs(u[0] - u0) < 1e-6 and abs(v[0] - v0) < 1e-6 and abs(z[0] - z0) < 1e-6


@pytest.mark.parametrize('yaw', [0.0, math.pi / 2, math.pi, -2.0])
def test_down_camera_ground_roundtrip_is_yaw_invariant(yaw):
    pos = np.array([4.5, 0.5, 1.2])
    marker = np.array([4.8, 0.2, 0.0])
    R = g.quat_to_R(*g.yaw_quat(yaw))
    # forward model under the documented convention
    p_body = R.T @ (marker - pos)
    p_cam = g.DOWN_CAM_R.T @ (p_body - g.DOWN_CAM_T)
    fx, fy, cx, cy = g.DOWN_INTRINSICS
    u, v = cx + fx * p_cam[0] / p_cam[2], cy + fy * p_cam[1] / p_cam[2]
    assert 0 <= u <= 640 and 0 <= v <= 480
    back = g.down_pixel_to_ground(u, v, pos, R)
    assert np.allclose(back, marker, atol=1e-6)


def test_down_camera_image_top_is_forward():
    pos, R = np.array([0.0, 0.0, 1.0]), np.eye(3)
    ahead = g.down_pixel_to_ground(320, 100, pos, R)     # above image centre
    assert ahead[0] > 0.3 and abs(ahead[1]) < 1e-9
    left = g.down_pixel_to_ground(100, 240, pos, R)      # left of image centre
    assert left[1] > 0.3 and abs(left[0]) < 1e-9


def test_down_camera_compensates_tilt():
    pos = np.array([1.0, 1.0, 1.5])
    pitch = math.radians(5)
    R = np.array([[math.cos(pitch), 0, math.sin(pitch)], [0, 1, 0],
                  [-math.sin(pitch), 0, math.cos(pitch)]])
    p = g.down_pixel_to_ground(320, 240, pos, R)
    # optical axis tilts; the hit point moves by h*tan(5 deg) ~ 0.13 m
    assert abs(abs(p[0] - 1.0) - 1.5 * math.tan(pitch)) < 1e-6


def test_robust_center():
    med, ok = g.robust_center([[1, 1, 0], [1.05, 0.95, 0], [0.98, 1.02, 0]])
    assert ok and np.allclose(med[:2], [1, 1], atol=0.05)
    _, ok = g.robust_center([[1, 1, 0], [2, 1, 0], [1, 1, 0]])
    assert not ok
