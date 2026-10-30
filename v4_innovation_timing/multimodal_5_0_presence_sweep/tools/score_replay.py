#!/usr/bin/env python3
"""Score servo-window replay dirs (P10/P11/P12 row format) with the Stage-A dev-gate metrics + miss decomposition."""
import glob, json, statistics as st, sys

for d in sys.argv[1:]:
    T = dict(vis=0, ok=0, pub=0, acq=0, wrong=0, dropped=0, absent=0, fp=0); area = []; tails = []; per = {}
    for f in sorted(glob.glob(d + "/*_baseline.json")):
        col = f.split("_")[-2]; P = per.setdefault(col, [0, 0, 0])
        R = json.load(open(f))["rows"]; acquired = False
        for r in R:
            g = r["gt"]
            if not isinstance(g, list):
                if g is None:
                    acquired = False; T["absent"] += 1; T["fp"] += bool(r["pub"])
                continue
            T["vis"] += 1; P[1] += 1
            if r["pub"]:
                T["pub"] += 1; P[2] += 1
                pa = (r["pub"][2] - r["pub"][0]) * (r["pub"][3] - r["pub"][1]); ga = (g[2] - g[0]) * (g[3] - g[1]); area.append(pa / ga)
            if r["pub"] and r["cin"]:
                T["ok"] += 1; P[0] += 1; acquired = True
            elif r["pub"]:
                T["wrong"] += 1
            elif not acquired:
                T["acq"] += 1
            else:
                T["dropped"] += 1
        # tail: publishes in the last continuous YOLO-absent stretch
        k = len(R) - 1; n = 0
        while k >= 0 and R[k]["gt"] is None:
            n += bool(R[k]["pub"]); k -= 1
        tails.append(n)
    print(f"{d}: centre {T['ok']}/{T['vis']}={T['ok']/T['vis']:.1%}  precision {T['ok']/max(1,T['pub']):.1%}  "
          f"area_med {st.median(area):.2f}  tail_max {max(tails)}  fp_absent {T['fp']}/{T['absent']}  "
          f"misses: acq {T['acq']} wrong {T['wrong']} dropped {T['dropped']}  " +
          " ".join(f"{c}:{v[0]}/{v[1]}" for c, v in sorted(per.items())))
