"""Pure geometry for the FM9G scene bridge.  No ROS, no torch: unit-testable.

Frame conventions (all verified against the official sources in this repo):

* World = ENU, the frame of `/rflysim/uav1/local/odom` (the same topic the BT
  nodes read through MavRosConnect, and the same one cloud_transform_node uses).
* Body  = FLU (x forward, y left, z up).
* Camera optical frame = (x right, y down, z forward).  The forward RGB camera
  `sensor1` maps optical->body with `cam2body_R = [0,0,1, -1,0,0, 0,-1,0]`
  (llm_mission.launch) and fx = fy = 320, cx = 320, cy = 240 (640x480, FOV 90).
* Depth cloud `/rflysim/sensor0/Depth_Cloud` is in the depth sensor frame, which
  cloud_transform_node treats as body-aligned FLU with offset (0.2, 0, 0)
  (Config.json SensorPosXYZ).  sensor1 is mounted at the same point.
* Downward camera `sensor2` (Config.json SensorAngEular [0,-90,0]) looks along
  body -z.  ASSUMED: image top = body forward.  `DOWN_CAM_R` encodes that; the
  handoff contains a yaw-invariance check that confirms or refutes it on the
  real simulator before any flight relies on it.
"""
import math

import numpy as np

FRONT_INTRINSICS = (320.0, 320.0, 320.0, 240.0)   # fx, fy, cx, cy
DOWN_INTRINSICS = (320.0, 320.0, 320.0, 240.0)
IMAGE_W, IMAGE_H = 640, 480

FRONT_CAM_R = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], dtype=float)
FRONT_CAM_T = np.array([0.1, 0.04, 0.05])
DEPTH_SENSOR_T = np.array([0.2, 0.0, 0.0])
# optical -> body for a camera looking straight down with image-top = forward:
# x_c (right) = -y_b, y_c (down) = -x_b, z_c (forward) = -z_b
DOWN_CAM_R = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]], dtype=float)
DOWN_CAM_T = np.array([0.0, 0.0, 0.0])


def quat_to_R(x, y, z, w):
    """Rotation matrix of a unit quaternion (ROS order x, y, z, w)."""
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-9:
        raise ValueError('zero quaternion')
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def yaw_quat(yaw):
    return (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))


# --------------------------------------------------------------------------
# FM9G native box format
# --------------------------------------------------------------------------
def native_to_pixels(vals, width=IMAGE_W, height=IMAGE_H):
    """FM9G4B-V native `<box>x1 y1 x2 y2</box>` is normalised to 0..1000."""
    x1, y1, x2, y2 = [float(v) for v in vals]
    if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
        raise ValueError('invalid native box %r' % (vals,))
    return [x1 * width / 1000.0, y1 * height / 1000.0,
            x2 * width / 1000.0, y2 * height / 1000.0]


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def touches_border(box, margin=5.0, width=IMAGE_W, height=IMAGE_H):
    """Same rule as TargetLocator::isPartiallyOutOfView."""
    return (box[0] < margin or box[1] < margin or
            box[2] > width - margin or box[3] > height - margin)


# --------------------------------------------------------------------------
# Forward camera: depth from the depth cloud
# --------------------------------------------------------------------------
def project_depth_points(points_sensor, intr=FRONT_INTRINSICS,
                         depth_T=DEPTH_SENSOR_T, cam_R=FRONT_CAM_R, cam_T=FRONT_CAM_T):
    """Project Nx3 depth-sensor points (FLU) into the forward RGB image.

    Returns (u, v, z_optical) arrays for points in front of the camera.
    """
    pts = np.asarray(points_sensor, dtype=float).reshape(-1, 3)
    body = pts + depth_T
    optical = (body - cam_T) @ cam_R       # R^T applied row-wise
    z = optical[:, 2]
    keep = z > 0.05
    optical, z = optical[keep], z[keep]
    fx, fy, cx, cy = intr
    u = cx + fx * optical[:, 0] / z
    v = cy + fy * optical[:, 1] / z
    return u, v, z


def box_depth(u, v, z, box, mode='solid', ring=0.22, min_points=15):
    """Robust optical-axis depth of the object inside `box`.

    solid  (pillar): 30th percentile of all points in the box.
    hollow (frame):  points in the outer ring of the box only, so rays through
                     the opening (which hit the far wall) are excluded; then the
                     20th percentile, i.e. the near surface.
    Returns (depth or None, n_points_used).
    """
    x1, y1, x2, y2 = box
    inside = (u >= x1) & (u <= x2) & (v >= y1) & (v <= y2)
    if mode == 'hollow':
        bw, bh = (x2 - x1) * ring, (y2 - y1) * ring
        core = (u > x1 + bw) & (u < x2 - bw) & (v > y1 + bh) & (v < y2 - bh)
        sel = inside & ~core
        pct = 20
    else:
        sel = inside
        pct = 30
    zs = z[sel]
    if zs.size < min_points:
        return None, int(zs.size)
    return float(np.percentile(zs, pct)), int(zs.size)


def size_depth(box, width_m, height_m, intr=FRONT_INTRINSICS):
    """What TargetLocator computes: physical size * f / pixel size (both axes)."""
    fx, fy, _, _ = intr
    pw, ph = box[2] - box[0], box[3] - box[1]
    if pw <= 0 or ph <= 0:
        return None, None
    return width_m * fx / pw, height_m * fy / ph


def depth_consistent(d_cloud, d_size, rel=0.15, abs_tol=0.25):
    """True when the box's size-implied depth agrees with the depth camera."""
    if d_cloud is None or d_size is None:
        return False
    return abs(d_cloud - d_size) <= max(abs_tol, rel * d_cloud)


def front_pixel_to_world(u, v, depth, pos, R_wb, intr=FRONT_INTRINSICS,
                         cam_R=FRONT_CAM_R, cam_T=FRONT_CAM_T):
    """Pixel + optical depth -> world ENU (mirrors PoseUtils::cameraToWorld)."""
    fx, fy, cx, cy = intr
    p_cam = np.array([(u - cx) * depth / fx, (v - cy) * depth / fy, depth])
    p_body = cam_R @ p_cam + cam_T
    return np.asarray(pos, dtype=float) + R_wb @ p_body


# --------------------------------------------------------------------------
# Downward camera: ground-plane intersection
# --------------------------------------------------------------------------
def down_pixel_to_ground(u, v, pos, R_wb, ground_z=0.0, intr=DOWN_INTRINSICS,
                         cam_R=DOWN_CAM_R, cam_T=DOWN_CAM_T):
    """Intersect the pixel ray of the downward camera with the plane z=ground_z.

    Uses full attitude, so moderate roll/pitch during hover is compensated.
    Returns world ENU point, or None when the ray does not hit the ground.
    """
    fx, fy, cx, cy = intr
    ray_cam = np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
    ray_w = R_wb @ (cam_R @ ray_cam)
    origin = np.asarray(pos, dtype=float) + R_wb @ cam_T
    if ray_w[2] > -1e-3:
        return None
    t = (ground_z - origin[2]) / ray_w[2]
    if t <= 0:
        return None
    return origin + t * ray_w


def ground_box_size_m(box, height_above_ground, intr=DOWN_INTRINSICS):
    """Approximate metric width/height of a ground box seen from straight above."""
    fx, fy, _, _ = intr
    return ((box[2] - box[0]) * height_above_ground / fx,
            (box[3] - box[1]) * height_above_ground / fy)


# --------------------------------------------------------------------------
# Sample aggregation (what the BT node does again in C++; kept here for tests)
# --------------------------------------------------------------------------
def robust_center(points, max_spread=0.25):
    """Median of samples, and whether all samples lie within max_spread of it."""
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    med = np.median(pts, axis=0)
    spread = np.max(np.linalg.norm(pts[:, :2] - med[:2], axis=1)) if len(pts) else math.inf
    return med, bool(spread <= max_spread)
