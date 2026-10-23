import json, glob, datetime as dt, statistics

def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z","+00:00"))

paths = sorted(glob.glob("v3_stability/reports/hit_balloon_part1_1.*/**/rosout_events.jsonl", recursive=True))
rows = []
for p in paths:
    with open(p, encoding="utf-8") as f:
        events = [json.loads(l) for l in f if l.strip()]
    stages = {}
    mission_start = mission_end = None
    takeoff_start = takeoff_end = None
    cross1_start = cross1_end = None
    aruco_goto_start = aruco_detected = None
    cross2_start = cross2_end = None
    sprint_start = None
    goto_origin_start = None
    land_start = land_end = None
    seen_planning_starts = 0
    seen_planning_ends = 0
    for e in events:
        t = e.get("wall_time")
        m = e.get("message","")
        if not t: continue
        if "Starting LLM Mission Execution" in m and mission_start is None:
            mission_start = parse(t)
        if "LLM Mission Completed" in m:
            mission_end = parse(t)
        if "[Takeoff]: Takeoff start" in m and takeoff_start is None:
            takeoff_start = parse(t)
        if "[Takeoff]: Takeoff completed." in m and takeoff_end is None:
            takeoff_end = parse(t)
        if "Planning navigation start" in m:
            seen_planning_starts += 1
            if seen_planning_starts == 1:
                cross1_start = parse(t)
            elif seen_planning_starts == 2:
                cross2_start = parse(t)
        if "Planning navigation completed." in m:
            seen_planning_ends += 1
            if seen_planning_ends == 1:
                cross1_end = parse(t)
            elif seen_planning_ends == 2:
                cross2_end = parse(t)
        if "ArUco Marker Detected" in m and aruco_detected is None:
            aruco_detected = parse(t)
        if "[VisualServo]: forward_vel=" in m and sprint_start is None:
            sprint_start = parse(t)
        if "target: (0.00, 0.00," in m and goto_origin_start is None and sprint_start is not None:
            goto_origin_start = parse(t)
        if "[Land]: Requesting mode AUTO.LAND" in m and land_start is None:
            land_start = parse(t)
        if "[Land]: Landed and disarmed." in m and land_end is None:
            land_end = parse(t)
    def d(a,b):
        return (b-a).total_seconds() if a and b else None
    rows.append({
        "path": p,
        "total": d(mission_start, mission_end),
        "takeoff": d(takeoff_start, takeoff_end),
        "cross_frame_1": d(cross1_start, cross1_end),
        "aruco_wait": d(cross1_end, aruco_detected),
        "return_cross_frame": d(cross2_start, cross2_end),
        "hit_balloon": d(sprint_start, goto_origin_start),
        "land": d(land_start, land_end),
    })

cols = ["total","takeoff","cross_frame_1","aruco_wait","return_cross_frame","hit_balloon","land"]
print(f"{'stage':<20}{'n':>4}{'mean':>8}{'median':>8}{'min':>8}{'max':>8}")
for c in cols:
    vals = [r[c] for r in rows if r[c] is not None and r[c] >= 0]
    if not vals: 
        print(f"{c:<20} no data")
        continue
    print(f"{c:<20}{len(vals):>4}{statistics.mean(vals):>8.1f}{statistics.median(vals):>8.1f}{min(vals):>8.1f}{max(vals):>8.1f}")

print()
print("per-trial:")
for r in rows:
    print(r["path"], {k: (round(v,1) if v is not None else None) for k,v in r.items() if k!="path"})
