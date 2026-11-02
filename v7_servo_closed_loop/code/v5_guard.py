"""L1/L2 publish guard for the FM9G balloon bridge.

The model stays the only detector; this module only decides what the bridge
*publishes* between model decisions, and it bounds what a bad box can command.

L1 continuity: publish at camera rate instead of going silent, with a hard
   0.9 s cap and a decaying confidence.
L2 sanity:
   - a box that touches the left/right/bottom border has a biased centre (the
     bottom-border case is what commanded -0.3 m/s and put the drone at 0.1 m),
     so its command is clamped to EDGE_*_PX instead of the measured offset;
   - a centre teleport inside 0.25 s is rejected (the last estimate is held);
   - below MIN_Z metres altitude the downward-looking offset is zeroed.
Nothing here commands flight and nothing here detects anything.
"""
import math

IMG_W, IMG_H = 640, 480
CX, CY = 320.0, 240.0


class PublishGuard:
    COAST_S = 0.35          # tracker's own freshness window: predict freely
    HOLD_MAX_S = 0.90       # beyond this a stale box is dropped (lost)
    HOLD_SCORE_MIN = 0.31
    ALPHA = 0.6             # alpha-beta filter on the box centre
    BETA = 0.15
    MAX_EXTRAP_PX = 40.0
    EDGE_PX = 2
    EDGE_X_PX = 60.0        # command cap for a border-touching box (was up to 300+)
    EDGE_Y_PX = 60.0
    JUMP_WINDOW_S = 0.25
    JUMP_PX = 120.0
    MIN_Z = 0.35            # metres; below this no descent may be commanded
    mode = 'idle'

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.reset(0)

    def reset(self, epoch):
        self.epoch = epoch
        self.box = None
        self.cx, self.cy = CX, CY
        self.vx = self.vy = 0.0
        self.t = None
        self.mode = 'idle'

    def apply(self, bbox, now, epoch, z=None):
        """bbox: (x1,y1,x2,y2) or None. Returns dict(bbox, score, mode, age_s, note) or None."""
        if not self.enabled:
            if bbox is None:
                return None
            return {'bbox': tuple(float(v) for v in bbox), 'score': 1.0,
                    'mode': 'off', 'age_s': 0.0, 'note': ''}
        if epoch != self.epoch:
            self.reset(epoch)
        note = []
        if bbox is not None:
            x1, y1, x2, y2 = [float(v) for v in bbox]
            if x2 - x1 < 2 or y2 - y1 < 2:
                bbox = None
            else:
                mcx, mcy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                dt = 0.0 if self.t is None else max(1e-3, now - self.t)
                jump = False
                if self.t is not None and dt <= self.JUMP_WINDOW_S:
                    pred_x, pred_y = self.cx + self.vx * dt, self.cy + self.vy * dt
                    jump = math.hypot(mcx - pred_x, mcy - pred_y) > self.JUMP_PX
                if jump:
                    note.append('jump_rejected')
                    bbox = None
                else:
                    w, h = x2 - x1, y2 - y1
                    edge = False
                    if x1 <= self.EDGE_PX or x2 >= IMG_W - self.EDGE_PX:
                        note.append('edge_x')
                        mcx = CX + math.copysign(min(abs(mcx - CX), self.EDGE_X_PX), mcx - CX)
                        edge = True
                    if y1 <= self.EDGE_PX or y2 >= IMG_H - self.EDGE_PX:
                        note.append('edge_y')
                        mcy = CY + math.copysign(min(abs(mcy - CY), self.EDGE_Y_PX), mcy - CY)
                        edge = True
                    mcx = min(max(mcx, w / 2.0), IMG_W - w / 2.0)
                    mcy = min(max(mcy, h / 2.0), IMG_H - h / 2.0)
                    if edge:
                        # A border hit is not a trustworthy centre: restart the
                        # filter there instead of learning from it.
                        self.vx = self.vy = 0.0
                    else:
                        pred_x, pred_y = self.cx + self.vx * dt, self.cy + self.vy * dt
                        rx, ry = mcx - pred_x, mcy - pred_y
                        self.vx = self.vx + (self.BETA / dt) * rx if dt > 0 else self.vx
                        self.vy = self.vy + (self.BETA / dt) * ry if dt > 0 else self.vy
                    self.cx, self.cy = mcx, mcy
                    self.box = (mcx - w / 2.0, mcy - h / 2.0, mcx + w / 2.0, mcy + h / 2.0)
                    self.t = now
                    return self._finish(self.box, 1.0,
                                        'live_clamped' if note else 'live', 0.0, note, z)
        if self.t is None:
            self.mode = 'none'
            return None
        age = now - self.t
        if age > self.HOLD_MAX_S:
            self.mode = 'lost'
            self.box = None
            self.t = None
            self.vx = self.vy = 0.0
            return None
        x1, y1, x2, y2 = self.box
        w, h = x2 - x1, y2 - y1
        mcx = (x1 + x2) / 2.0 + max(-self.MAX_EXTRAP_PX, min(self.MAX_EXTRAP_PX, self.vx * age))
        mcy = (y1 + y2) / 2.0 + max(-self.MAX_EXTRAP_PX, min(self.MAX_EXTRAP_PX, self.vy * age))
        mcx = min(max(mcx, w / 2.0), IMG_W - w / 2.0)
        mcy = min(max(mcy, h / 2.0), IMG_H - h / 2.0)
        out = (mcx - w / 2.0, mcy - h / 2.0, mcx + w / 2.0, mcy + h / 2.0)
        if age <= self.COAST_S:
            score, mode = 1.0, 'coast'
        else:
            frac = (age - self.COAST_S) / (self.HOLD_MAX_S - self.COAST_S)
            score = max(self.HOLD_SCORE_MIN, 1.0 - (1.0 - self.HOLD_SCORE_MIN) * frac)
            mode = 'hold'
        note.append('predicted')
        return self._finish(out, score, mode, age, note, z)

    def _finish(self, box, score, mode, age, note, z):
        x1, y1, x2, y2 = box
        if z is not None and z < self.MIN_Z:
            mcy = (y1 + y2) / 2.0
            # Do not merely stop sinking: command a gentle climb back up
            # (the offset is what the visual servo turns into vertical speed).
            target = CY - self.EDGE_Y_PX
            if mcy > target:
                shift = target - mcy
                y1, y2 = y1 + shift, y2 + shift
                if y1 < 0:
                    y2 -= y1
                    y1 = 0.0
                if y2 > IMG_H:
                    y1 -= y2 - IMG_H
                    y2 = float(IMG_H)
                note = note + ['alt_climb']
        self.mode = mode
        return {'bbox': (x1, y1, x2, y2), 'score': score, 'mode': mode,
                'age_s': age, 'note': ','.join(note)}
