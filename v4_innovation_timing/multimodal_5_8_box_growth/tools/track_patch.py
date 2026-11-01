"""Patched track() for NativePresenceSweep (presence.py).

Change: when the first sweep finds >=1 edge that never crosses (the target extends past the window on that
side), AND the window is still small (<400 px), re-sweep once in a 2x window around the same center
(ONE bounded retry, no state carried across decision cycles). If that retry succeeds (p0 still >=0.5), use ITS
edges. The size clamp (0.85-1.25x previous) is skipped ONLY for this retried result when at least one edge
still fails to cross even in the larger window -- i.e. only when there is direct evidence the target is
genuinely larger than the un-retried window, not on every ordinary tracking step.

Everything else (thresholds, shape prior, minimum size, aspect clamp) is unchanged from the original.
"""


def track(self, frame_bgr, text, previous_box, epoch, decision, session, color, frame_seq, stamp):
    cx = (previous_box[0] + previous_box[2]) / 2
    cy = (previous_box[1] + previous_box[3]) / 2
    side = max(56, self.window_factor * max(previous_box[2] - previous_box[0], previous_box[3] - previous_box[1]))
    window = self.square(cx, cy, side)
    images, positions = self.sweep_imgs(frame_bgr, window, self.n_track)
    probabilities = self.call(images, text, epoch, decision, session, color, frame_seq, stamp, "track_sweep", [window])
    box, p0, curves = self.edge_box(probabilities, positions, window, self.thresholds)
    self.audit(kind="presence_sweep", decision=decision, session=session, color=color, stage="track_sweep",
               frame_seq=frame_seq, p0=p0, curves=curves, thresholds=self.thresholds, box=box, window=window,
               positions=positions)
    if p0 < 0.5:
        return None

    def edges_of(curves, p0):
        xs = [0.0] + positions
        out = []
        for profile, threshold in zip(curves, self.thresholds):
            value = None
            for j in range(1, len(profile)):
                if profile[j - 1] >= threshold * p0 > profile[j]:
                    fraction = (profile[j - 1] - threshold * p0) / (profile[j - 1] - profile[j] + 1e-9)
                    value = xs[j - 1] + fraction * (xs[j] - xs[j - 1])
                    break
            out.append(value)
        return out

    c = edges_of(curves, p0)
    retried = False
    # Bounded single retry: if >=1 edge never crossed and the window is still small, double it once.
    if sum(e is None for e in c) >= 1 and side < 400:
        side2 = min(400, 2.0 * side)
        window2 = self.square(cx, cy, side2)
        images2, positions2 = self.sweep_imgs(frame_bgr, window2, self.n_track)
        probabilities2 = self.call(images2, text, epoch, decision, session, color, frame_seq, stamp,
                                   "track_sweep_retry", [window2])
        box2, p0b, curves2 = self.edge_box(probabilities2, positions2, window2, self.thresholds)
        self.audit(kind="presence_sweep", decision=decision, session=session, color=color,
                   stage="track_sweep_retry", frame_seq=frame_seq, p0=p0b, curves=curves2,
                   thresholds=self.thresholds, box=box2, window=window2, positions=positions2)
        if p0b >= 0.5:
            xs2 = [0.0] + positions2

            def edges_of2(curves, p0):
                out = []
                for profile, threshold in zip(curves, self.thresholds):
                    value = None
                    for j in range(1, len(profile)):
                        if profile[j - 1] >= threshold * p0 > profile[j]:
                            fraction = (profile[j - 1] - threshold * p0) / (profile[j - 1] - profile[j] + 1e-9)
                            value = xs2[j - 1] + fraction * (xs2[j] - xs2[j - 1])
                            break
                    out.append(value)
                return out
            window, c, p0 = window2, edges_of2(curves2, p0b), p0b
            retried = True

    left, right, top, bottom = c
    side_px = window[2] - window[0]
    trust_window = retried and sum(e is None for e in c) >= 1
    if trust_window:
        candidate = [window[0] + side_px - right if right is not None else window[0],
                     window[1] + side_px - bottom if bottom is not None else window[1],
                     window[0] + left if left is not None else window[2],
                     window[1] + top if top is not None else window[3]]
    else:
        candidate = [window[0] + side_px - right if right is not None else previous_box[0],
                     window[1] + side_px - bottom if bottom is not None else previous_box[1],
                     window[0] + left if left is not None else previous_box[2],
                     window[1] + top if top is not None else previous_box[3]]
    if candidate[2] <= candidate[0] + 2 or candidate[3] <= candidate[1] + 2:
        return list(previous_box)
    old_w, old_h = previous_box[2] - previous_box[0], previous_box[3] - previous_box[1]
    width, height = candidate[2] - candidate[0], candidate[3] - candidate[1]
    if not trust_window:
        width = min(max(width, 0.85 * old_w), 1.25 * old_w)
        height = min(max(height, 0.85 * old_h), 1.25 * old_h)
    cx = (candidate[0] + candidate[2]) / 2
    cy = (candidate[1] + candidate[3]) / 2
    width, height = max(width, 12.0), max(height, 12.0)
    if height < 0.9 * width:
        cy, height = cy - (0.9 * width - height) / 2, 0.9 * width
    if height > 1.6 * width:
        width = height / 1.6
    return [cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2]
