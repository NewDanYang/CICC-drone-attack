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

v6.7 evidence (purple trial 20261102T132246, audit 20261102T052308_ed6e12):
  * A decision lands 1.0-1.3 s after the frame it was made on (0.5 s sweep plus
    the queue wait), and measure() used that source time as the measurement
    clock.  publish() then applied MAX_AGE_S=1.2 s to that clock, so a box that
    arrived with age 1.06 s stayed publishable for 0.14 s and the next one
    arrived already expired.  55 of 500 publications carried a box (11%), the
    behaviour tree saw no target for more than 1 s between sweeps and
    VisualServo spent the stage in "Target lost. Position-held search".
  * Fix: the publication lifetime is measured from ARRIVAL, while the box is
    still extrapolated from the source frame through the pose log.
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
    # The clock that matters is when the answer ARRIVED, not when its pixels
    # were captured: the sweep needs ~0.5 s plus the queue wait, so a
    # frame-time clock expires a box before the next one can land.
    EXPIRE_S = 4.00           # keep steering on the estimate between measurements
    MAX_AGE_S = 1.35          # old name, same meaning
    LIVE_AGE_S = 0.70         # full confidence up to here, measured from arrival
    # Close-range commitment: once the balloon covers the view the model
    # under-reports its box (224-px tiles, window crossings), and the
    # 0.5 s pipeline cannot wait for the last honest 8%.  A big box near
    # the axis means the balloon is right in front: report it centred and
    # at a size the servo accepts, which is what the servo's own gate
    # would conclude one frame later.
    COMMIT_HEIGHT_PX = 130.0
    COMMIT_AREA = 0.060
    COMMIT_AGE_S = 1.10
    COMMIT_AXIS_PX = 170.0
    COMMIT_MIN_AREA = 0.100

    SCORE_LIVE = 1.00
    SCORE_HOLD = 0.86         # above the 0.8 gate of the behaviour tree
    STALE_VIEW_S = 3.00       # keep the crop window around it, re-acquire beyond this
    # Vertical safety: the balloon rides on a cart, so centring it drags the
    # drone down to cart height.  Below MIN_ALT_M the carried box is nudged up
    # so the vertical loop stops descending instead of chasing the floor.
    MIN_ALT_M = 0.35
    ALT_PUSH_PX = 45.0
    # Motion compensation
    FOCAL_DEFAULT = 650.0     # px; 2*atan(320/650) = 52 deg horizontal FOV
    FOCAL_MIN = 400.0
    FOCAL_MAX = 1100.0
    THETA_LIMIT = 1.40        # rad, keeps tan() finite at the frame edge
    BALLOON_M = 0.30          # nominal balloon diameter, only used for the dz term
    MAX_DV = 45.0
    # v7.0 motion model: the *measured* image velocity, not the odometry yaw.
    # Trial 20261102T141320 (audit 20261102T061338_729c64) turned at 0.05 rad
    # per 1.2 s in the odom log while the static checkerboard pillar under the
    # camera moved 3 px (0.005 rad): the odom yaw does not describe the camera.
    # Carrying the box with it walked the box +85 px the wrong way, the crop
    # window left the balloon, and 4.7 s passed without a measurement -- which
    # is exactly the 4.0 s EXPIRE_S window.  Replaying 45 real measurement
    # pairs: yaw carry median error 31.3 px / p90 87 px; damped image velocity
    # 16.5 px / 55 px.  So the carry is image space, damped, and bounded.
    MAX_VX = 350.0            # px/s cap on a single noisy pair
    CARRY_DAMP = 0.5          # the target accelerates; half the velocity travels better
    MAX_LEAD_X = 80.0         # px, hard bound on the carried displacement
    MAX_LEAD_Y = 45.0
    HORIZON_S = 1.20          # beyond this the carried box stops moving
    SIZE_GROWTH_MAX = 1.80
    # Crop window
    WINDOW_FACTOR = 3.00
    WINDOW_MIN = 200.0
    WINDOW_MAX = 470.0
    GROWTH_MAX = 1.60
    # Perspective carry: the pixel offset from the optical axis grows as 1/Z.
    # Z is recovered from the size ratio and the translation along the line of
    # sight, so no metric calibration is needed.
    CARRY_MAX = 2.50
    RANGE_MIN = 0.10
    RANGE_MAX = 12.0
    CX_MIN = 180.0
    CX_MAX = 560.0
    # Model geometry is only trustworthy away from the border: a balloon that
    # leaves the image is still "there" for the model, which then answers with
    # a sliver pinned to the edge.  Its centre is a hundred pixels off and the
    # servo dives at that phantom, so those axes follow the prediction instead.
    EDGE_PX = 3.0
    JUMP_PX = 180.0
    SIZE_MIN_RATIO = 0.62
    SIZE_MAX_RATIO = 2.20

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
        self.hist = deque(maxlen=3)

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
        if previous is not None and acquired - previous['acquired'] > 2.0:
            # A long gap: the range estimate belongs to another flight leg.
            previous = None
            self.range_m = None
        clipped_x = x1 <= self.EDGE_PX or x2 >= IMG_W - self.EDGE_PX
        clipped_y = y1 <= self.EDGE_PX or y2 >= IMG_H - self.EDGE_PX
        if previous is not None:
            predicted = self.predict(acquired)
            draft = {'bbox': (x1, y1, x2, y2), 'acquired': acquired,
                     'arrived': time.monotonic(),
                     'decision': decision, 'seq': seq}
            self._update_focal(previous, draft)
            self._update_geometry(previous, draft)
            x1, y1, x2, y2 = self._fuse(previous, (x1, y1, x2, y2), clipped_x,
                                        clipped_y, predicted, acquired,
                                        decision, seq)
        current = {'bbox': (x1, y1, x2, y2), 'acquired': acquired,
                   'arrived': time.monotonic(),
                   'decision': decision, 'seq': seq}
        self.prev_meas = previous
        self.meas = current
        self.hist.append((current['acquired'], (x1 + x2) / 2.0,
                          (y1 + y2) / 2.0, x2 - x1, y2 - y1))
        return self.meas

    def _fuse(self, previous, box, clipped_x, clipped_y, predicted, acquired,
              decision, seq):
        """Keep the model's verdict, distrust its geometry at the frame edge."""
        mx1, my1, mx2, my2 = box
        mw, mh = mx2 - mx1, my2 - my1
        mcx, mcy = (mx1 + mx2) / 2.0, (my1 + my2) / 2.0
        if predicted is None:
            self.audit(kind='v6_residual', decision=decision, seq=seq,
                       dt=None, residual=None, clipped=[clipped_x, clipped_y])
            return box
        px1, py1, px2, py2 = predicted
        pw, ph = px2 - px1, py2 - py1
        pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
        under_x = mw < self.SIZE_MIN_RATIO * pw
        under_y = mh < self.SIZE_MIN_RATIO * ph
        if clipped_x or under_x:
            width = pw
        else:
            width = clamp(mw, self.SIZE_MIN_RATIO * pw,
                          self.SIZE_MAX_RATIO * pw)
        if clipped_y or under_y:
            height = ph
        else:
            height = clamp(mh, self.SIZE_MIN_RATIO * ph,
                           self.SIZE_MAX_RATIO * ph)
        cx = pcx if clipped_x else clamp(mcx, pcx - self.JUMP_PX,
                                         pcx + self.JUMP_PX)
        cy = pcy if clipped_y else clamp(mcy, pcy - self.JUMP_PX,
                                         pcy + self.JUMP_PX)
        p0 = self.pose_at(previous['acquired'])
        p1 = self.pose_at(acquired)
        self.audit(kind='v6_residual', decision=decision, seq=seq,
                   dt=acquired - previous['acquired'],
                   dyaw=wrap_pi(p1[4] - p0[4]) if p0 and p1 else None,
                   dz=(p1[3] - p0[3]) if p0 and p1 else None,
                   predicted=[pcx, pcy], observed=[mcx, mcy],
                   residual=[mcx - pcx, mcy - pcy],
                   focal=self.focal,
                   previous_size=[previous['bbox'][2] - previous['bbox'][0],
                                  previous['bbox'][3] - previous['bbox'][1]],
                   observed_size=[mw, mh], clipped=[bool(clipped_x), bool(clipped_y)],
                   undercoverage=[bool(under_x), bool(under_y)])
        width = min(width, float(IMG_W))
        height = min(height, float(IMG_H))
        cx = clamp(cx, width / 2.0, IMG_W - width / 2.0)
        cy = clamp(cy, height / 2.0, IMG_H - height / 2.0)
        fused = (cx - width / 2.0, cy - height / 2.0,
                 cx + width / 2.0, cy + height / 2.0)
        if (abs(fused[0] - mx1) > 1.0 or abs(fused[1] - my1) > 1.0 or
                abs(fused[2] - mx2) > 1.0 or abs(fused[3] - my2) > 1.0):
            self.audit(kind='v6_fuse', decision=decision, seq=seq,
                       clipped=[bool(clipped_x), bool(clipped_y)],
                       undercoverage=[bool(under_x), bool(under_y)],
                       measured=[mcx, mcy, mw, mh],
                       predicted=[pcx, pcy, pw, ph],
                       fused=[cx, cy, width, height])
        return fused

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
    def _velocity(self):
        """Measured image velocity of the box centre, px/s (v7.0)."""
        if len(self.hist) < 2:
            return 0.0, 0.0
        t0, cx0, cy0, _w0, _h0 = self.hist[-2]
        t1, cx1, cy1, _w1, _h1 = self.hist[-1]
        dt = t1 - t0
        if dt <= 0.05 or dt > 2.0:
            return 0.0, 0.0
        return (clamp((cx1 - cx0) / dt, -self.MAX_VX, self.MAX_VX),
                clamp((cy1 - cy0) / dt, -self.MAX_VX, self.MAX_VX))

    def _growth(self):
        """Fractional size growth per second from the last two measurements."""
        if len(self.hist) < 2:
            return 0.0
        t0, _cx0, _cy0, w0, h0 = self.hist[-2]
        t1, _cx1, _cy1, w1, h1 = self.hist[-1]
        dt = t1 - t0
        if dt <= 0.05 or dt > 2.0 or w0 < 4.0 or h0 < 4.0:
            return 0.0
        return clamp((max(w1 / w0, h1 / h0) - 1.0) / dt, 0.0, 1.5)

    def measured_center(self):
        if self.meas is None:
            return None
        x1, y1, x2, y2 = self.meas['bbox']
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def predict(self, t):
        if self.meas is None:
            return None
        x1, y1, x2, y2 = self.meas['bbox']
        width, height = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        age = clamp(t - self.meas['acquired'], 0.0, self.HORIZON_S)
        vx, vy = self._velocity()
        cx = cx + clamp(self.CARRY_DAMP * vx * age,
                        -self.MAX_LEAD_X, self.MAX_LEAD_X)
        cy = cy + clamp(self.CARRY_DAMP * vy * age,
                        -self.MAX_LEAD_Y, self.MAX_LEAD_Y)
        grow = clamp(1.0 + self._growth() * age, 1.0, self.SIZE_GROWTH_MAX)
        width = min(width * grow, float(IMG_W))
        height = min(height * grow, float(IMG_H))
        dv = 0.0
        p0 = self.pose_at(self.meas['acquired'])
        p1 = self.pose_at(t)
        if p0 is not None and p1 is not None:
            # Climbing by dz moves the target down by f*dz/Z, and f/Z is the
            # box height over the nominal balloon diameter.  Near contact the
            # box is under-reported, so fade the term out as the target fills
            # the view.
            fade = clamp(1.0 - (height - 80.0) / 160.0, 0.0, 1.0)
            dv = clamp((p1[3] - p0[3]) * height / self.BALLOON_M,
                       -self.MAX_DV, self.MAX_DV) * fade
        cy = cy + dv
        cx = clamp(cx, width / 2.0, IMG_W - width / 2.0)
        cy = clamp(cy, height / 2.0, IMG_H - height / 2.0)
        return (cx - width / 2.0, cy - height / 2.0,
                cx + width / 2.0, cy + height / 2.0)

    # ------------------------------------------------------------ publish
    def altitude(self, now):
        if not self.poses:
            return None
        last = self.poses[-1]
        if now - last[0] > 0.60:
            return None
        return last[3]

    def _commit_box(self, arrival_age):
        """The balloon fills the view: hand the servo a box it can act on."""
        if self.meas is None or arrival_age > self.COMMIT_AGE_S:
            return None
        x1, y1, x2, y2 = self.meas['bbox']
        w, h = x2 - x1, y2 - y1
        area = (w * h) / float(IMG_W * IMG_H)
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if h < self.COMMIT_HEIGHT_PX and area < self.COMMIT_AREA:
            return None
        if abs(cx - CX) > self.COMMIT_AXIS_PX or abs(cy - CY) > self.COMMIT_AXIS_PX:
            return None
        grow = 1.0
        if area < self.COMMIT_MIN_AREA:
            grow = math.sqrt(self.COMMIT_MIN_AREA / max(area, 1e-6))
        w = min(w * grow, float(IMG_W))
        h = min(h * grow, float(IMG_H))
        self.audit(kind='v6_commit', age_s=arrival_age, raw_area=area,
                   raw_size=[x1, y1, x2, y2], committed=[CX - w / 2, CY - h / 2,
                                                         CX + w / 2, CY + h / 2],
                   grow=grow)
        return (CX - w / 2.0, CY - h / 2.0, CX + w / 2.0, CY + h / 2.0)

    def publish(self, now):
        if self.meas is None:
            return None
        arrived = self.meas.get('arrived', self.meas['acquired'])
        arrival_age = now - arrived
        evidence_age = now - self.meas['acquired']
        if arrival_age > self.EXPIRE_S:
            return None
        box = self.predict(now)
        if box is None:
            return None
        alt = self.altitude(now)
        if alt is not None and alt < self.MIN_ALT_M:
            dy = clamp((self.MIN_ALT_M - alt) / self.MIN_ALT_M, 0.0, 1.0) * self.ALT_PUSH_PX
            y1, y2 = box[1] - dy, box[3] - dy
            if y1 < 0.0:
                y2 = y2 - y1
                y1 = 0.0
            box = (box[0], y1, box[2], y2)
        commit = self._commit_box(arrival_age)
        if commit is not None:
            box = commit
            mode = 'commit'
        elif arrival_age <= self.LIVE_AGE_S:
            mode = 'live'
        else:
            mode = 'hold'
        score = self.SCORE_LIVE if mode != 'hold' else self.SCORE_HOLD
        return {'bbox': box, 'score': float(score), 'mode': mode,
                'age_s': arrival_age,
                'decision': self.meas['decision'], 'seq': self.meas['seq'],
                'meas_bbox': self.meas['bbox'],
                'arrival_age_s': arrival_age,
                'semantic_age_s': evidence_age}

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
                'stale_s': t - self.meas['acquired'], 'focal': self.focal,
                'alt_center': self.measured_center()}
