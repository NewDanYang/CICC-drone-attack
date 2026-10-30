#!/usr/bin/env python3
"""Score P7 rows: fit per-direction crossing thresholds on split=train only, report validation and test (run10)."""
import itertools, json, math, statistics as st, sys

rows = [json.loads(l) for l in open(sys.argv[1])]
COL = ("red", "purple", "blue")


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def ce(a, b):
    return math.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2)


def gate(p, t):
    return iou(p, t) >= 0.5 and ce(p, t) <= max(8, 0.2 * math.hypot(t[2] - t[0], t[3] - t[1]))


def cross(prof, xs, t, S):
    for j in range(1, len(prof)):
        if prof[j - 1] >= t > prof[j]:
            a = (prof[j - 1] - t) / (prof[j - 1] - prof[j] + 1e-9); return xs[j - 1] + a * (xs[j] - xs[j - 1])
    return float(S)


def box(r, th):
    """th = relative thresholds for (L,R,T,B) sweeps."""
    if "ps2" not in r or r["ps2"][0] < 0.5:
        return None
    ps, pos, W = r["ps2"], r["pos2"], r["W2"]; S = W[2] - W[0]; n = len(pos); p0 = ps[0]
    c = [cross([p0] + ps[1 + k * n:1 + (k + 1) * n], [0.0] + pos, th[k] * p0, S) for k in range(4)]
    cL, cR, cT, cB = c
    b = [W[0] + S - cR, W[1] + S - cB, W[0] + cL, W[1] + cT]
    return b if b[2] > b[0] + 1 and b[3] > b[1] + 1 else None


def evaluate(D, th):
    out = []
    for r in D:
        b = box(r, th); g = r["gt"]
        out.append(dict(r=r, b=b, gate=bool(b) and gate(b, g), cin=bool(b) and g[0] <= (b[0] + b[2]) / 2 <= g[2] and g[1] <= (b[1] + b[3]) / 2 <= g[3],
                        ce=ce(b, g) if b else None, iou=iou(b, g) if b else 0))
    return out


P = [r for r in rows if r["present"] and r.get("gt")]
N = [r for r in rows if not r["present"]]
tr = [r for r in P if r["split"] == "train"]
grid = [0.3, 0.4, 0.5, 0.6, 0.7]
best = None
# horizontal and vertical thresholds fit separately (independent edges) by train gate count, tie-break mean IoU
for th in itertools.product(grid, grid, grid, grid):
    e = evaluate(tr, th); s = (sum(x["gate"] for x in e), sum(x["iou"] for x in e))
    if best is None or s > best[0]:
        best = (s, th)
th = best[1]
print("rows", len(rows), "train pos", len(tr), "fitted thresholds L,R,T,B =", th, "train gate", best[0][0])
for split in ("train", "validation", "test"):
    D = [r for r in P if r["split"] == split]
    if not D:
        continue
    for name, t in (("thr=0.5", (0.5,) * 4), ("fitted", th)):
        e = evaluate(D, t)
        cs = [x["ce"] for x in e if x["ce"] is not None]
        print(f"{split:10s} {name:8s} gate {sum(x['gate'] for x in e)}/{len(D)}  cin {sum(x['cin'] for x in e)}  "
              f"cerr_med {st.median(cs) if cs else float('nan'):.1f}  iou_med {st.median([x['iou'] for x in e]):.2f}  " +
              " ".join(f"{c}:{sum(x['gate'] for x in e if x['r']['color'] == c)}/{sum(x['r']['color'] == c for x in e)}" for c in COL) +
              f"  small<40:{sum(x['gate'] for x in e if max(x['r']['gt'][2]-x['r']['gt'][0], x['r']['gt'][3]-x['r']['gt'][1]) < 40)}/"
              f"{sum(max(x['r']['gt'][2]-x['r']['gt'][0], x['r']['gt'][3]-x['r']['gt'][1]) < 40 for x in e)}")
for split in ("train", "validation", "test"):
    D = [r for r in P if r["split"] == split]; Ns = [r for r in N if r["split"] == split]
    if D:
        print(f"{split:10s} presence full>=.5 pos {sum(r['p_full'] >= .5 for r in D)}/{len(D)} neg {sum(r['p_full'] >= .5 for r in Ns)}/{len(Ns)}; "
              f"tile-ROI found pos {sum('roi' in r for r in D)}/{len(D)} neg {sum('roi' in r for r in Ns)}/{len(Ns)}; s1 invalid {sum(r.get('s1_invalid', False) for r in D)}")
cc = [p for r in rows if "cross" in r for o, p in r["cross"].items() if r["other_px"][o] < 20]
print("cross-colour false yes on fine windows (other colour absent by HSV):", f"{sum(p >= .5 for p in cc)}/{len(cc)}")
T = [r for r in rows if "t_total" in r]
print("latency median s: full %.3f tiles %.3f s1 %.3f s2 %.3f total %.3f cross %.3f" % tuple(
    st.median([r[k] for r in T]) for k in ("t_full", "t_tiles", "t_s1", "t_s2", "t_total", "t_cross")),
    " p90 total %.3f" % sorted(r["t_total"] for r in T)[int(.9 * len(T))])
json.dump(dict(thresholds=th), open(sys.argv[1] + ".fit.json", "w"))
