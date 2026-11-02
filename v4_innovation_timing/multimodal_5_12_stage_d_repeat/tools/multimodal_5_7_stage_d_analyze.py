#!/usr/bin/env python3
import csv
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/tcei_baseline_tools")
COLLECT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "results" / "stage_d_20261101_retry"
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else COLLECT / "analysis"
OUT.mkdir(parents=True, exist_ok=True)

LANE_TOL = 0.40


def read_jsonl(path):
    rows = []
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    except Exception:
        pass
    return rows


def read_kv(path):
    d = {}
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
    except Exception:
        pass
    return d


def classify_pos(pos):
    # CORRECTED 2026-11-02 (see multimodal_5_7_stage_d/REPORT.md erratum and
    # multimodal_5_11_synthesis/REPORT.md): this was previously y=+2.1->red,
    # y=-2.1->purple, verified backwards against real candidate camera frames
    # (a red-mission trial tracked and destroyed a visibly red balloon that
    # was the y=-2.1 actor; a purple-mission trial tracked and destroyed a
    # visibly purple balloon that was the y=+2.1 actor). This hardcoded
    # lane->color guess was never calibrated against this UE instance
    # (judgement.json literally says "no unique color calibration for this
    # UE instance and roster") -- if the roster/instance changes again,
    # re-verify against real frames before trusting this mapping, don't just
    # assume it still holds.
    x, y = float(pos[0]), float(pos[1])
    # The blue lane is the x=5.6 edge lane and can cross y=+/-2.1,
    # so test it before the red/purple y lanes.
    if abs(x - 5.6) <= LANE_TOL:
        return "blue"
    if abs(y - 2.1) <= LANE_TOL:
        return "purple"
    if abs(y + 2.1) <= LANE_TOL:
        return "red"
    return "unknown"


def scene_verdict(session, expected):
    snap = read_jsonl(session / "scene_snapshots.jsonl")
    before = next((x for x in snap if x.get("phase") == "before"), None)
    settled = next((x for x in reversed(snap) if x.get("phase") == "settled"), None)
    before_ids = (before or {}).get("actor_ids", [])
    settled_ids = (settled or {}).get("actor_ids", [])
    pos = {}
    try:
        payload = json.loads((session / "actor_positions.json").read_text(encoding="utf-8", errors="replace"))
        for name, obj in (payload.get("objects") or {}).items():
            pos[name] = obj.get("pos_ue")
        if not settled_ids:
            settled_ids = payload.get("actor_ids_after", [])
    except Exception:
        payload = {}
    lanes = []
    for name in settled_ids:
        if name in pos:
            lanes.append(classify_pos(pos[name]))
    lanes = [x for x in lanes if x != "unknown"]
    uniq = sorted(set(lanes))
    removed = len(set(before_ids) - set(settled_ids)) if before_ids else max(0, 3 - len(settled_ids))
    missing = ""
    if len(settled_ids) == 2 and len(uniq) == 2:
        missing = ({"red", "purple", "blue"} - set(uniq)).pop()
    if removed == 1 and missing in {"red", "purple", "blue"}:
        hit = int(missing == expected)
        verdict = "hit" if hit else "wrong_lane"
    elif removed == 0:
        hit, verdict, missing = 0, "no_deletion", "none"
    elif removed > 1:
        hit, verdict, missing = 0, "extra_deletion", missing or "unknown"
    else:
        hit, verdict, missing = 0, "unresolved", missing or "unknown"
    return {
        "before_count": len(before_ids), "settled_count": len(settled_ids),
        "removed_count": removed, "surviving_lanes": ",".join(uniq),
        "missing_lane": missing, "verdict": verdict, "hit": hit,
        "before_ids": before_ids, "settled_ids": settled_ids,
        "actor_position_error": payload.get("error", "") if isinstance(payload, dict) else "",
    }


def raw_metrics(trial):
    obs = read_kv(trial / "observer.out")
    try:
        otxt = (trial / "observer.out").read_text(encoding="utf-8", errors="replace")
        mobj = re.search(r"(?ms)^\{\s*\n.*?^\}\s*$", otxt)
        if mobj:
            j = json.loads(mobj.group(0))
            obs.update({str(k): str(v) for k, v in j.items()})
    except Exception:
        pass
    raw = obs.get("raw_log", "")
    rows = read_jsonl(raw) if raw else []
    msgs = [str(x.get("message", "")) for x in rows if x.get("event") == "rosout"]
    states = [m for m in msgs if "[VisualServo]:" in m]
    approach = sum("[VisualServo]: APPROACH -" in m for m in msgs)
    aligned = sum("[VisualServo]: Aligned!" in m for m in msgs)
    align = sum("[VisualServo]: ALIGN -" in m for m in msgs)
    sprint_start = sum("SPRINT_START" in m for m in msgs)
    sprint_end = sum("SPRINT_END" in m for m in msgs)
    search = sum("Position-held search" in m for m in msgs)
    multimodal_pixel = sum("MULTIMODAL_PIXEL" in m for m in msgs)
    model_call = sum(any(k in m for k in ("presence_model_call", "model_call", "presence inference")) for m in msgs)
    mission_lines = ""
    try:
        mission_lines = (trial / "mission_once.out").read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    multimodal_pixel += mission_lines.count("MULTIMODAL_PIXEL")
    model_call += mission_lines.count("presence_model_call") + mission_lines.count("model_call")
    boundary = obs.get("safety_boundary_triggered", "")
    from datetime import datetime
    def ts(x):
        try:
            return datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except Exception:
            return None
    search_times = [ts(x.get("wall_time")) for x in rows if x.get("event") == "rosout" and "Position-held search" in str(x.get("message", ""))]
    search_times = [x for x in search_times if x is not None]
    search_duration = 0.0
    if search_times:
        groups = [[search_times[0]]]
        for t in search_times[1:]:
            if (t - groups[-1][-1]).total_seconds() <= 2.2:
                groups[-1].append(t)
            else:
                groups.append([t])
        for g in groups:
            if len(g) >= 2:
                gaps = [(b-a).total_seconds() for a,b in zip(g, g[1:])]
                search_duration += (g[-1]-g[0]).total_seconds() + statistics.median(gaps)
    aligned_rows = [x for x in rows if x.get("event") == "rosout" and "[VisualServo]: Aligned!" in str(x.get("message", ""))]
    first_aligned_wall = aligned_rows[0].get("wall_time", "") if aligned_rows else ""
    start_dt = ts(obs.get("start_time", ""))
    first_aligned_rel = ""
    if start_dt and first_aligned_wall:
        adt = ts(first_aligned_wall)
        if adt:
            first_aligned_rel = f"{(adt-start_dt).total_seconds():.3f}"
    return {
        "run_id": obs.get("run_id", ""),
        "start_time": obs.get("start_time", ""),
        "total_time": float(obs.get("total_time", "nan")) if obs.get("total_time") else math.nan,
        "mission_success": obs.get("mission_success", ""),
        "failure_stage": obs.get("failure_stage", ""),
        "boundary": boundary,
        "boundary_count": obs.get("boundary_violation_count", "0"),
        "approach_count": approach,
        "aligned_count": aligned,
        "align_count": align,
        "sprint_start_count": sprint_start,
        "sprint_end_count": sprint_end,
        "search_count": search,
        "search_duration_s": f"{search_duration:.3f}",
        "first_aligned_wall": first_aligned_wall,
        "first_aligned_rel_s": first_aligned_rel,
        "multimodal_pixel_count": multimodal_pixel,
        "model_call_count": model_call,
        "never_approach": int(approach == 0),
        "visual_state_tail": states[-1] if states else "",
        "raw_log": raw,
    }


def find_audit(run_id, start_time=""):
    if not run_id and not start_time:
        return "", 0, "", ""
    root = ROOT / "results" / "multimodal_v2"
    best = ("", 0, "", float("inf"))
    try:
        from datetime import datetime
        target = datetime.fromisoformat(start_time.replace("Z", "+00:00")) if start_time else None
    except Exception:
        target = None
    for d in root.glob("*"):
        p = d / "audit.jsonl"
        if not p.is_file():
            continue
        rows = read_jsonl(p)
        if not rows:
            continue
        first = rows[0].get("wall_time", "")
        try:
            first_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
            distance = abs((first_dt - target).total_seconds()) if target else 0.0
        except Exception:
            distance = float("inf")
        if distance < best[3]:
            best = (str(p), len(rows), first, distance)
    return best[:3]


def audit_latency(path):
    vals = []
    for x in read_jsonl(path) if path else []:
        if x.get("kind") == "presence_model_call":
            try:
                vals.append(float(x["latency_s"]))
            except Exception:
                pass
    vals.sort()
    if not vals:
        return 0, "", ""
    med = statistics.median(vals)
    p90 = vals[max(0, math.ceil(0.90 * len(vals)) - 1)]
    return len(vals), f"{med:.6f}", f"{p90:.6f}"


def main():
    manifest = COLLECT / "manifest.tsv"
    rows = []
    with manifest.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("pair") not in {"1", "2", "3"}:
                continue
            trial = Path(r["trial_dir"])
            label = f"p{r['pair']}_{r['condition']}_{r['color']}"
            session = COLLECT / f"session_{label}"
            v = scene_verdict(session, r["color"])
            m = raw_metrics(trial)
            status = read_kv(session / "status.txt")
            r = {**r, **v, **m, "gc_rc": status.get("gc_rc", ""), "session": str(session)}
            if r["condition"] == "candidate":
                ap, ac, af = find_audit(r.get("run_id", ""), r.get("start_time", ""))
                ak = {}
                al = ""
                if ap:
                    arows = read_jsonl(ap)
                    al = arows[-1].get("kind", "") if arows else ""
                    for x in arows:
                        k = x.get("kind", "")
                        ak[k] = ak.get(k, 0) + 1
                lcount, lmed, lp90 = audit_latency(ap)
                r.update({"audit_path": ap, "audit_rows": ac, "audit_first": af,
                          "audit_last_kind": al, "audit_kinds": ",".join(sorted(ak)),
                          "model_call_audit_count": lcount, "model_latency_median_s": lmed,
                          "model_latency_p90_s": lp90})
            else:
                r.update({"audit_path": "", "audit_rows": 0, "audit_first": "", "audit_last_kind": "", "audit_kinds": "", "model_call_audit_count": 0, "model_latency_median_s": "", "model_latency_p90_s": ""})
            rows.append(r)
    fields = ["pair", "color", "condition", "trial_rc", "trial_dir", "before_count", "settled_count", "removed_count", "surviving_lanes", "missing_lane", "verdict", "hit", "total_time", "mission_success", "failure_stage", "boundary", "boundary_count", "approach_count", "aligned_count", "align_count", "sprint_start_count", "sprint_end_count", "search_count", "search_duration_s", "first_aligned_wall", "first_aligned_rel_s", "multimodal_pixel_count", "model_call_count", "model_call_audit_count", "model_latency_median_s", "model_latency_p90_s", "never_approach", "gc_rc", "run_id", "start_time", "raw_log", "audit_path", "audit_rows", "audit_first", "audit_last_kind", "audit_kinds"]
    with (OUT / "metrics.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    with (OUT / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    for condition in ("candidate", "baseline"):
        sub = [r for r in rows if r["condition"] == condition]
        times = [r["total_time"] for r in sub if not math.isnan(r["total_time"])]
        print(condition, "n=", len(sub), "hits=", sum(int(r["hit"]) for r in sub), "never_approach=", sum(int(r["never_approach"]) for r in sub), "median_time=", statistics.median(times) if times else None)
        for color in ("red", "purple", "blue"):
            ss = [r for r in sub if r["color"] == color]
            print(" ", color, "hits=", sum(int(r["hit"]) for r in ss), "/", len(ss), "verdicts=", ",".join(r["verdict"] for r in ss))


if __name__ == "__main__":
    main()
