"""v6 target estimator: one measurement source (the FM9G box), carried by pose.

The model stays the only detector.  This module answers one question: where is
the balloon *now*, given the last box the model produced and how the camera has
moved since then.  There is no CSRT, no replay and no second tracker in this
path, so nothing can drift away from the model while it is not looking.

v6.2 evidence (purple trial 20261102T113123, audit 20261102T033148_cdcb25):
  * The balloon swept u=39 -> 284 -> 387 -> 532 px while the drone turned at
    the commanded 0.301 rad/s.  The old linear carry du = K*dyaw (K=320) with a
    +-140 px clamp predicted 150+ px short, so the crop window looked at empty
    wall: 29 sweep crops scored p=0.12..0.22 while the same frames score
    p=0.87 on a correctly placed window.
  * Replaying those sweeps: linear K=320 -> mean |err| 105 px (max 207);
    linear K=650 -> 26 px; bearing space u = CX + F*tan(theta) with F=650 ->
    24.8 px (max 51), F=750 -> 24.9 px.  So the carry is done in bearing space
    and F is calibrated online from consecutive measurements.
  * score must stay >= 0.8 for the whole life of a carried box: the behaviour
    tree asks MultimodalTargetTracker for confidence_threshold="0.8" and the
    C++ node drops every object below it (multimodal_target_tracker.cpp:67).
"""
import math
import time
from collections import deque

IMG_W, IMG_H = 640, 480
CX, CY = IMG_W / 2.0, IMG_H / 2.0


def clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def wrap_pi(angle):
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


class TargetEstimator:
    # Publishing
    MAX_AGE_S = 1.20          # publish a carried box at most this long after its frame
    LIVE_AGE_S = 0.60         # full confidence up to here
    SCORE_LIVE = 1.00
    SCORE_HOLD = 0.86         # above the 0.8 gate of the behaviour tree
    STALE_VIEW_S = 3.00       # keep the crop window around it, re-acquire beyond this
    # Motion compensation
    FOCAL_DEFAULT = 650.0     # px; 2*atan(320/650) = 52 deg horizontal FOV
    FOCAL_MIN = 400.0
    FOCAL_MAX = 1100.0
    THETA_LIMIT = 1.40        # rad, keeps tan() finite at the frame edge
    BALLOON_M = 0.30          # nominal balloon diameter, only used for the dz term
    MAX_DV = 60.0
    # Crop window
    WINDOW_FACTOR = 2.60
    WINDOW_MIN = 140.0
    WINDOW_MAX = 360.0
    GROWTH_MAX = 1.60
    # Perspective carry: the pixel offset from the optical axis grows as 1/Z.
    # Z is recovered from the size ratio and the translation along the line of
    # sight, so no metric calibration is needed.
    CARRY_MAX = 2.50
    RANGE_MIN = 0.10
    RANGE_MAX = 12.0
    CX_MIN = 180.0
    CX_MAX = 560.0

    def __init__(self, audit=None):
        self.audit = audit or (lambda **event: None)
        self.poses = deque(maxlen=1200)
        self.focal = self.FOCAL_DEFAULT
        self.focal_samples = deque(maxlen=60)
        self.principal_samples = deque(maxlen=9)
        self.range_samples = deque(maxlen=9)
        self.reset(0)

    def reset(self, epoch):
        self.epoch = epoch
        self.meas = None
        self.prev_meas = None
        self.cx_eff = float(CX)
        self.range_m = None
        self.principal_samples.clear()
        self.range_samples.clear()

    # ---------------------------------------------------------------- pose
    def on_pose(self, now, x, y, z, yaw):
        self.poses.append((now, x, y, z, yaw))

    def pose_at(self, t):
        if not self.poses:
            return None
        best = self.poses[0]
        for sample in self.poses:
            if sample[0] <= t:
                best = sample
            else:
                break
        return best

    def z_now(self):
        return self.poses[-1][3] if self.poses else None

    # -------------------------------------------------------------- focal
    def _solve_focal(self, u0, u1, dyaw):
        """F such that atan((u1-CX)/F) - atan((u0-CX)/F) == dyaw, or None."""
        if abs(dyaw) < 0.02:
            return None

        def residual(focal):
            return (math.atan2(u1 - CX, focal) - math.atan2(u0 - CX, focal)
                    - dyaw)

        low, high = 150.0, 40000.0
        if residual(low) * residual(high) > 0.0:
            return None
        for _ in range(60):
            mid = 0.5 * (low + high)
            if residual(low) * residual(mid) <= 0.0:
                high = mid
            else:
                low = mid
        return 0.5 * (low + high)

    def _update_focal(self, previous, current):
        p0 = self.pose_at(previous['acquired'])
        p1 = self.pose_at(current['acquired'])
        if p0 is None or p1 is None:
            return
        dyaw = wrap_pi(p1[4] - p0[4])
        if abs(dyaw) < 0.02 or abs(dyaw) > 1.20:
            return
        u0 = (previous['bbox'][0] + previous['bbox'][2]) / 2.0
        u1 = (current['bbox'][0] + current['bbox'][2]) / 2.0
        if not (4.0 < u0 < IMG_W - 4.0 and 4.0 < u1 < IMG_W - 4.0):
            return
        focal = self._solve_focal(u0, u1, dyaw)
        if focal is None or not (self.FOCAL_MIN <= focal <= self.FOCAL_MAX):
            return
        self.focal_samples.append(focal)
        ordered = sorted(self.focal_samples)
        if len(ordered) >= 3:
            self.focal = ordered[len(ordered) // 2]
        self.audit(kind='v6_focal', sample=focal, focal=self.focal,
                   samples=len(ordered), u0=u0, u1=u1, dyaw=dyaw)

    def _update_geometry(self, previous, current):
        """Range and principal point, from two boxes and the flown distance.

        The apparent size of a rigid object scales as 1/Z, so the ratio of two
        box heights fixes the range in metres given how far the drone moved
        between the two views -- no focal length or object size needed.  The
        same pair gives the pixel column the perspective expansion is centred
        on, which is where the camera axis actually sits.
        """
        h0 = previous['bbox'][3] - previous['bbox'][1]
        h1 = current['bbox'][3] - current['bbox'][1]
        if h0 < 6.0 or h1 < 6.0:
            return
        u0 = (previous['bbox'][0] + previous['bbox'][2]) / 2.0
        u1 = (current['bbox'][0] + current['bbox'][2]) / 2.0
        if abs(h1 - h0) > 5.0:
            guess = (u0 * h1 - u1 * h0) / (h1 - h0)
            if self.CX_MIN < guess < self.CX_MAX:
                self.principal_samples.append(guess)
                ordered = sorted(self.principal_samples)
                self.cx_eff = ordered[len(ordered) // 2]
                self.audit(kind='v6_principal', guess=guess, cx_eff=self.cx_eff,
                           samples=len(ordered))
        p0 = self.pose_at(previous['acquired'])
        p1 = self.pose_at(current['acquired'])
        if p0 is None or p1 is None:
            return
        if abs(wrap_pi(p1[4] - p0[4])) > 0.50:
            return
        travel = math.hypot(p1[1] - p0[1], p1[2] - p0[2])
        if travel < 0.03 or h1 <= h0 * 1.03:
            return
        before = travel / (1.0 - h0 / h1)
        if not (self.RANGE_MIN < before < self.RANGE_MAX):
            return
        self.range_samples.append(before * h0 / h1)
        ordered = sorted(self.range_samples)
        self.range_m = ordered[len(ordered) // 2]
        self.audit(kind='v6_range', travel=travel, ratio=h1 / h0, before=before,
                   range_m=self.range_m, samples=len(ordered))

    # --------------------------------------------------------- measurement
    def measure(self, bbox, acquired, decision=None, seq=None):
        if bbox is None or len(bbox) != 4:
            return None
        x1, y1, x2, y2 = [float(v) for v in bbox]
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        previous = self.meas
        current = {'bbox': (x1, y1, x2, y2), 'acquired': acquired,
                   'decision': decision, 'seq': seq}
        if previous is not None and acquired - previous['acquired'] > 2.0:
            # A long gap: the range estimate belongs to another flight leg.
            previous = None
            self.range_m = None
        if previous is not None:
            self._update_focal(previous, current)
            self._update_geometry(previous, current)
            predicted = self.predict(acquired)
            observed = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            guess = ((predicted[0] + predicted[2]) / 2.0,
                     (predicted[1] + predicted[3]) / 2.0)
            p0 = self.pose_at(previous['acquired'])
            p1 = self.pose_at(acquired)
            self.audit(kind='v6_residual', decision=decision, seq=seq,
                       dt=acquired - previous['acquired'],
                       dyaw=wrap_pi(p1[4] - p0[4]) if p0 and p1 else None,
                       dz=(p1[3] - p0[3]) if p0 and p1 else None,
                       predicted=guess, observed=observed,
                       residual=(observed[0] - guess[0], observed[1] - guess[1]),
                       focal=self.focal,
                       previous_size=[previous['bbox'][2] - previous['bbox'][0],
                                      previous['bbox'][3] - previous['bbox'][1]],
                       observed_size=[x2 - x1, y2 - y1])
        self.prev_meas = previous
        self.meas = current
        return self.meas

    def view(self):
        """Last model box, in the shape the old model_track dict had."""
        if self.meas is None:
            return None
        age = time.monotonic() - self.meas['acquired']
        if age > self.STALE_VIEW_S:
            return None
        return {'bbox': list(self.meas['bbox']),
                'semantic_age_s': age,
                'source_acquired': self.meas['acquired'],
                'decision': self.meas['decision'],
                'seq': self.meas['seq'],
                'raw_bbox': list(self.meas['bbox']),
                'visible_fraction': 1.0}

    # ------------------------------------------------------------ predict
    def predict(self, t):
        if self.meas is None:
            return None
        x1, y1, x2, y2 = self.meas['bbox']
        width, height = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        dv = 0.0
        p0 = self.pose_at(self.meas['acquired'])
        p1 = self.pose_at(t)
        scale = 1.0
        if p0 is not None and p1 is not None:
            dyaw = wrap_pi(p1[4] - p0[4])
            theta = math.atan2(cx - CX, self.focal) + dyaw
            cx = CX + self.focal * math.tan(
                clamp(theta, -self.THETA_LIMIT, self.THETA_LIMIT))
            # Climbing by dz moves the target down by f*dz/Z, and f/Z is the
            # box height over the nominal balloon diameter.
            dv = clamp((p1[3] - p0[3]) * height / self.BALLOON_M,
                       -self.MAX_DV, self.MAX_DV)
            if self.range_m is not None:
                # Closing the range by `travel` magnifies everything about the
                # camera axis by Z/(Z-travel): the box grows, and its centre
                # moves away from that axis.  Without this the window keeps
                # pointing where the balloon used to be.
                travel = math.hypot(p1[1] - p0[1], p1[2] - p0[2])
                room = max(self.range_m - travel, 0.14)
                scale = clamp(self.range_m / room, 0.70, self.CARRY_MAX)
        if abs(scale - 1.0) > 0.001:
            cx = self.cx_eff + (cx - self.cx_eff) * scale
            cy = CY + (cy - CY) * scale
            width = width * scale
            height = height * scale
        cy = cy + dv
        width = min(width, float(IMG_W))
        height = min(height, float(IMG_H))
        cx = clamp(cx, width / 2.0, IMG_W - width / 2.0)
        cy = clamp(cy, height / 2.0, IMG_H - height / 2.0)
        return (cx - width / 2.0, cy - height / 2.0,
                cx + width / 2.0, cy + height / 2.0)

    # ------------------------------------------------------------ publish
    def publish(self, now):
        if self.meas is None:
            return None
        age = now - self.meas['acquired']
        if age > self.MAX_AGE_S:
            return None
        box = self.predict(now)
        if age <= self.LIVE_AGE_S:
            score, mode = self.SCORE_LIVE, 'live'
        else:
            score, mode = self.SCORE_HOLD, 'hold'
        return {'bbox': box, 'score': float(score), 'mode': mode, 'age_s': age,
                'decision': self.meas['decision'], 'seq': self.meas['seq'],
                'meas_bbox': self.meas['bbox'],
                'semantic_age_s': age}

    # --------------------------------------------------------------- crop
    def crop_params(self, t):
        if self.meas is None:
            return None
        predicted = self.predict(t)
        width = predicted[2] - predicted[0]
        height = predicted[3] - predicted[1]
        growth = 1.0
        if self.prev_meas is not None:
            pw = self.prev_meas['bbox'][2] - self.prev_meas['bbox'][0]
            ph = self.prev_meas['bbox'][3] - self.prev_meas['bbox'][1]
            growth = clamp(max((self.meas['bbox'][2] - self.meas['bbox'][0]) / max(pw, 1.0),
                               (self.meas['bbox'][3] - self.meas['bbox'][1]) / max(ph, 1.0)),
                           1.0, self.GROWTH_MAX)
        side = clamp(self.WINDOW_FACTOR * max(width, height) * growth,
                     self.WINDOW_MIN, self.WINDOW_MAX)
        center = ((predicted[0] + predicted[2]) / 2.0,
                  (predicted[1] + predicted[3]) / 2.0)
        return {'center': center, 'side': side,
                'stale_s': t - self.meas['acquired'], 'focal': self.focal}
