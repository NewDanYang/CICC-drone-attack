import json, os, glob, sys, collections

trial = sys.argv[1] if len(sys.argv) > 1 else None
root = "/home/ubuntu/tcei_baseline_tools/results"
if trial is None:
    cands = sorted(glob.glob(root + "/formal_trials/2*"))
    trial = cands[-1]
print("TRIAL", trial)
base = os.path.basename(trial.rstrip("/"))

# --- result files
for name in ("observer.out", "mission_once.out"):
    p = os.path.join(trial, name)
    if os.path.exists(p):
        txt = open(p, errors="replace").read()
        keys = [l for l in txt.splitlines() if any(k in l for k in
                ("mission_success", "failure_stage", "bt_success", "elapsed",
                 "hit_balloon_status", "notes"))]
        print("--", name)
        for l in keys[-14:]:
            print("   ", l.strip()[:200])

# --- logs
logs = sorted(glob.glob(trial + "/logs/*.jsonl"))
if not logs:
    print("no logs"); sys.exit(0)
lg = logs[-1]
print("LOG", os.path.basename(lg))
events = collections.Counter()
rosout = []
nd = 0
for line in open(lg, errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    ev = d.get("event")
    events[ev] += 1
    if ev == "rosout":
        rosout.append((d.get("wall_time", "")[11:23], d.get("message", "") or d.get("msg", "")))
print("events", dict(events))

def show(pred, limit=200, label=""):
    n = 0
    print("-- rosout", label)
    for t, m in rosout:
        if pred(m):
            print("   ", t, m[:170]); n += 1
            if n >= limit: break
    if n == 0: print("    (none)")

show(lambda m: "VisualServo" in m or "visual servo" in m.lower(), 12, "stage start")
show(lambda m: ("Aligned" in m) or ("APPROACH" in m) or ("Sprint" in m) or ("SPRINT" in m), 40, "align/approach/sprint")
show(lambda m: "lost" in m.lower() and "target" in m.lower(), 6, "target lost")
show(lambda m: "MULTIMODAL_STAGE" in m, 4, "stage boundaries")

# --- audit dir: newest
ads = sorted(glob.glob(root + "/multimodal_v2/*"), key=os.path.getmtime)
if not ads:
    print("no audit"); sys.exit(0)
ad = ads[-1]
print("AUDIT", ad)
kinds = collections.Counter(); modes = collections.Counter(); guard = collections.Counter()
meas = []; pubs = []; probs = []
for line in open(ad + "/audit.jsonl", errors="replace"):
    try:
        o = json.loads(line)
    except Exception:
        continue
    k = o.get("kind"); kinds[k] += 1
    if k == "decision": modes[o.get("mode")] += 1
    if k == "v6_measure": meas.append(o)
    if k == "publish":
        guard[o.get("guard_mode")] += 1
        if o.get("bbox"):
            pubs.append(o)
    if k in ("track_sweep", "acquire_tiles") and "p0" in o:
        probs.append((o.get("wall_time", "")[11:22], k, round(o.get("p0") or 0, 3)))
print("kinds", dict(kinds))
print("modes", dict(modes), "guard", dict(guard))
print("publish with bbox", len(pubs), "of", sum(guard.values()))
best = []
for p in pubs:
    x1, y1, x2, y2 = p["bbox"]
    a = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1)) / (640.0 * 480.0)
    best.append((a, p.get("wall_time", "")[11:22], p.get("guard_mode"), [round(v, 1) for v in p["bbox"]]))
best.sort(reverse=True)
print("top published areas:")
for a, t, g, bb in best[:12]:
    print("   %.4f %s %s %s" % (a, t, g, bb))
print("v6_measure", len(meas))
for m in meas[:60]:
    print("   ", m.get("wall_time", "")[11:22], m.get("mode"), "age", round(m.get("age") or 0, 2),
          "bbox", [round(v, 1) for v in (m.get("bbox") or [])], "yaw", round(m.get("yaw") or 0, 3))
hi = [p for p in probs if p[2] >= 0.5]
print("sweep p0>=0.5:", len(hi), "of", len(probs), "max", max([p[2] for p in probs], default=None))
