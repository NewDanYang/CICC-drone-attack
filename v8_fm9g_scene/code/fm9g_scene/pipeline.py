"""ROS-free decision logic shared by the flight bridge and the offline evaluator,
so offline numbers are produced by exactly the gates used in flight."""
from . import geometry as geo


def select_candidates(spec, boxes, probs):
    """Boxes (pixels) that pass the verify threshold, best first.
    Single-instance targets keep only the best box."""
    ranked = sorted(zip(boxes, probs), key=lambda bp: -bp[1])
    ranked = [(b, p) for b, p in ranked if p >= spec.verify_threshold]
    return ranked if spec.multi else ranked[:1]


def localise(spec, box, score, pos, R, cloud_points=None):
    """Metric localisation + gates for one verified box.

    pos, R: drone position (ENU) and body->world rotation at the image stamp.
    cloud_points: Nx3 depth-sensor points synchronous with the image (front only).
    Returns a dict; r['accepted'] is True only if every gate passed.
    """
    r = {'box': [round(float(v), 1) for v in box], 'score': round(float(score), 3), 'accepted': False}
    cu, cv = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    if spec.camera == 'front':
        if spec.name == 'square_frame' and geo.touches_border(box):
            r['reject'] = 'touches_border'
            return r
        if cloud_points is None:
            r['reject'] = 'no_synchronous_depth'
            return r
        u, v, z = geo.project_depth_points(cloud_points)
        depth, n = geo.box_depth(u, v, z, box, mode=spec.depth_mode)
        r.update(depth=depth, depth_points=n)
        if depth is None:
            r['reject'] = 'too_few_depth_points'
            return r
        if spec.name == 'square_frame':
            dw, dh = geo.size_depth(box, spec.width_m, spec.height_m)
            r['size_depth'] = [dw, dh]
            # Both axes must agree with the depth camera: the 2026-11-02
            # oversized/misplaced box fails exactly this gate.
            if not (geo.depth_consistent(depth, dw) and geo.depth_consistent(depth, dh)):
                r['reject'] = 'size_depth_mismatch'
                return r
        world = geo.front_pixel_to_world(cu, cv, depth, pos, R)
    else:
        world = geo.down_pixel_to_ground(cu, cv, pos, R)
        if world is None:
            r['reject'] = 'no_ground_hit'
            return r
        w_m, h_m = geo.ground_box_size_m(box, pos[2])
        r['size_m'] = [round(w_m, 3), round(h_m, 3)]
        lo, hi = spec.size_range_m
        if not (lo <= w_m <= hi and lo <= h_m <= hi):
            r['reject'] = 'implausible_ground_size'
            return r
    r.update(world=[round(float(c), 3) for c in world], accepted=True)
    return r
