"""Edge-extraction rules for occlusion sweep profiles. profile[0] = unmasked p0, then n masked samples at xs[1:]."""


def first_cross(prof, xs, t, S):
    for j in range(1, len(prof)):
        if prof[j - 1] >= t > prof[j]:
            a = (prof[j - 1] - t) / (prof[j - 1] - prof[j] + 1e-9)
            return xs[j - 1] + a * (xs[j] - xs[j - 1])
    return None


def step_cross(prof, xs, t, S):
    """Least-squares step fit: high (p0) before c, low after. Robust to single-sample spikes/dips.
    Returns None if no split beats 'no drop' (all high)."""
    hi = prof[0]
    best, bc = sum((p - hi) ** 2 for p in prof), None          # no drop at all
    for j in range(1, len(prof)):
        before = prof[:j]; after = prof[j:]
        lo = sum(after) / len(after)
        if lo >= t:      # the 'low' level must actually be below threshold
            continue
        e = sum((p - hi) ** 2 for p in before) + sum((p - lo) ** 2 for p in after)
        if e < best:
            best, bc = e, j
    if bc is None:
        return None
    # interpolate inside the step interval at threshold
    a, b = prof[bc - 1], prof[bc]
    f = (a - t) / (a - b + 1e-9) if a > b else 0.5
    f = min(max(f, 0.0), 1.0)
    return xs[bc - 1] + f * (xs[bc] - xs[bc - 1])


def box_from(ps, pos, W, th, rule="first", fallback=False, prev=None):
    S = W[2] - W[0]; n = len(pos); p0 = ps[0]
    if p0 < 0.5:
        return None
    xs = [0.0] + list(pos); fn = first_cross if rule == "first" else step_cross
    c = [fn([p0] + list(ps[1 + k * n:1 + (k + 1) * n]), xs, th[k] * p0, S) for k in range(4)]
    cL, cR, cT, cB = c
    if prev is None:
        cL = S if cL is None else cL; cR = S if cR is None else cR
        cT = S if cT is None else cT; cB = S if cB is None else cB
        x0, x1 = W[0] + S - cR, W[0] + cL; y0, y1 = W[1] + S - cB, W[1] + cT
    else:
        x0 = W[0] + S - cR if cR is not None else prev[0]; y0 = W[1] + S - cB if cB is not None else prev[1]
        x1 = W[0] + cL if cL is not None else prev[2]; y1 = W[1] + cT if cT is not None else prev[3]
    if fallback:
        # inverted axis: the two edges crossed; keep their midpoint as centre, size from the other axis (balloon ~round)
        if x1 <= x0 + 2 and y1 > y0 + 2:
            cx = (x0 + x1) / 2; w = max(12.0, (y1 - y0) / 1.2); x0, x1 = cx - w / 2, cx + w / 2
        elif y1 <= y0 + 2 and x1 > x0 + 2:
            cy = (y0 + y1) / 2; h = max(12.0, (x1 - x0) * 1.2); y0, y1 = cy - h / 2, cy + h / 2
    if x1 <= x0 + 2 or y1 <= y0 + 2:
        return None
    return [x0, y0, x1, y1]
