#!/usr/bin/env python3
"""Per-trial centre% across jitter seeds: median and worst, per config. usage: score_seeds.py PREFIX_v0 PREFIX_v1 ..."""
import glob, json, statistics as st, sys
from collections import defaultdict

for prefix in sys.argv[1:]:
    per = defaultdict(list)
    for d in sorted(glob.glob(prefix + "_s*")):
        for f in glob.glob(d + "/*_baseline.json"):
            R = json.load(open(f))["rows"]
            vis = [r for r in R if isinstance(r["gt"], list)]
            if not vis:
                continue
            ok = sum(bool(r["pub"] and r["cin"]) for r in vis)
            per[f.split("/")[-1].split("\\")[-1].replace(".json", "")].append(round(100 * ok / len(vis), 1))
    print(f"== {prefix}  seeds={len(glob.glob(prefix + '_s*'))}")
    col = defaultdict(list)
    for t, v in sorted(per.items()):
        print(f"  {t:24s} {v}  median {st.median(v):.1f}  worst {min(v):.1f}  range {max(v)-min(v):.1f}")
        col[t.split("_")[2]] += v
    for c, v in sorted(col.items()):
        print(f"  [{c}] all {len(v)} values  median {st.median(v):.1f}  worst {min(v):.1f}")
