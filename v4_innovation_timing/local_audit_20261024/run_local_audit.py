"""Read-only local audit. Python 3.12+, standard library only; no ROS/network calls.

Usage: python run_local_audit.py --repo PATH --out RESULT_DIR [--zip SNAPSHOT.zip]
Recorded model outputs are replayed, never regenerated. No flight is performed.
"""
import argparse
import contextlib
import csv
import datetime as dt
import difflib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import runpy
import statistics
import subprocess
import sys
import tarfile
import types
import zipfile


def hashes(path):
    data = path.read_bytes()
    return {"bytes": len(data), "md5": hashlib.md5(data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_module(path):
    for name in ("transformers", "torch", "rospy", "std_msgs", "std_msgs.msg"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["transformers"].AutoModel = object
    sys.modules["transformers"].AutoTokenizer = object
    sys.modules["std_msgs.msg"].String = object
    spec = importlib.util.spec_from_file_location("mission_audit_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--zip", type=Path)
    args = ap.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    if out == repo or repo in out.parents:
        ap.error("Place output outside the source repository.")
    out.mkdir(parents=True, exist_ok=True)
    evidence = out / "evidence"
    evidence.mkdir(exist_ok=True)
    provenance = {"time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "python": sys.version, "platform": platform.platform(),
                  "repository": ".", "repository_path_basis": "repository root",
                  "mode": "offline; no flight; no live model inference"}
    if args.zip:
        provenance["source_zip"] = hashes(args.zip)
        with zipfile.ZipFile(args.zip) as archive:
            provenance["commit"] = archive.comment.decode()
            provenance["expanded_bytes"] = sum(e.file_size for e in archive.infolist())
    audit = {"provenance": provenance}
    source_paths = set()

    # Verify the byte-preserving deployment archive, not Git-normalized copies.
    freeze = repo / "v3_stability/reports/hit_balloon_part1_final/source/final_deployment.tar.gz"
    source_paths.add(freeze)
    frozen = evidence / "frozen_source"
    frozen.mkdir(exist_ok=True)
    with tarfile.open(freeze) as archive:
        archive.extractall(frozen, filter="data")
    manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    checks = []
    for relative, expected in manifest["files"].items():
        got = hashes(frozen / relative)
        checks.append({"file": relative, **got,
                       "matches_manifest": all(got[k] == expected[k] for k in got)})
        baseline = repo / "official_baseline" / relative
        if baseline.exists():
            source_paths.add(baseline)
            diff = difflib.unified_diff(
                baseline.read_text(encoding="utf-8-sig").splitlines(True),
                (frozen / relative).read_text(encoding="utf-8-sig").splitlines(True),
                fromfile="official_baseline/" + relative,
                tofile="frozen_20261019/" + relative)
            (evidence / (Path(relative).name + ".diff")).write_text("".join(diff), encoding="utf-8")
    audit["frozen_integrity"] = checks
    extra = []
    for rel in ["official_baseline/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py",
                "v3_stability/rule_compliance/deploy/aruco_detect_node.py",
                "v3_stability/rule_compliance/deploy/mission_once.py",
                "v3_stability/aruco/aruco_detect_node.py",
                "v3_stability/aruco/aruco_detect_node.py.original"]:
        path = repo / rel
        source_paths.add(path)
        extra.append({"file": rel, **hashes(path)})
    audit["additional_source_hashes"] = extra
    planner_dir = repo / "v4_innovation_timing/path_planning_experiment"
    planner_manifest = planner_dir / "evidence/deploy_v1_manifest.json"
    source_paths.add(planner_manifest)
    planner_hashes = []
    for entry in json.loads(planner_manifest.read_text(encoding="utf-8"))["files"]:
        path = repo / "official_baseline/catkin_ws/src/ego-planner" / entry["relative"]
        source_paths.add(path)
        got = hashes(path)
        lf_bytes = path.read_bytes().replace(b"\r\n", b"\n")
        planner_hashes.append({"file": path.relative_to(repo).as_posix(), **got,
                               "matches_original": got["md5"] == entry["original_md5"],
                               "matches_candidate": got["md5"] == entry["deployed_md5"],
                               "lf_md5": hashlib.md5(lf_bytes).hexdigest(),
                               "crlf_md5": hashlib.md5(lf_bytes.replace(b"\n", b"\r\n")).hexdigest(),
                               "expected_original_md5": entry["original_md5"],
                               "expected_candidate_md5": entry["deployed_md5"]})
    audit["planner_baseline_provenance"] = planner_hashes

    # Run unchanged repository regression scripts in isolated subprocesses.
    tests = []
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               MISSION_MAX_ATTEMPTS="3", MISSION_RETRY_BUDGET_S="60")
    for name in ["test_mission_once_fallback.py", "test_aruco_display_loop.py"]:
        script = repo / "v3_stability/rule_compliance/tests" / name
        source_paths.add(script)
        result = subprocess.run([sys.executable, "-B", str(script)], cwd=repo, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        (evidence / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        tests.append({"script": script.relative_to(repo).as_posix(), "exit_code": result.returncode,
                      "passed_assertions": len(re.findall(r"^PASS ", result.stdout, re.M)),
                      "failed_assertions": len(re.findall(r"^FAIL ", result.stdout, re.M))})
    audit["repository_regressions"] = tests

    # Re-run the repository's own timing extraction on its real recorded logs.
    timing_script = repo / "v4_innovation_timing/evidence/stage_timing.py"
    source_paths.add(timing_script)
    old_cwd = Path.cwd()
    buffer = io.StringIO()
    try:
        os.chdir(repo)
        with contextlib.redirect_stdout(buffer):
            timing = runpy.run_path(str(timing_script), run_name="offline_audit")
    finally:
        os.chdir(old_cwd)
    (evidence / "stage_timing_rerun.txt").write_text(buffer.getvalue(), encoding="utf-8")
    timing_rows = timing["rows"]
    for row in timing_rows:
        source_paths.add(repo / row["path"])
        row["path"] = Path(row["path"]).as_posix()
    write_csv(evidence / "stage_timing_trials.csv", timing_rows)
    summaries = []
    for col in timing["cols"]:
        values = [row[col] for row in timing_rows if row[col] is not None and row[col] >= 0]
        summaries.append({"stage": col, "n": len(values), "mean_s": statistics.mean(values),
                          "median_s": statistics.median(values), "min_s": min(values), "max_s": max(values)})
    audit["historical_stage_timing"] = {"trials": len(timing_rows), "stages": summaries,
        "near_50s_count_tolerance_0p1s": sum(row["hit_balloon"] is not None and abs(row["hit_balloon"] - 50) <= 0.1 for row in timing_rows)}
    write_csv(evidence / "stage_timing_summary.csv", summaries)

    # Reproduce the three historical planning measurements using the original script.
    script = planner_dir / "tools/summarize_poc.py"
    source_paths.add(script)
    planning = []
    for label, data_name, csv_name, kind in [
        ("official", "feasibility_baseline_20261020.jsonl", "baseline_red_planning_runs.csv", "baseline_probe"),
        ("v1", "bridge_v1_red_20261020.jsonl", "v1_red_planning_runs.csv", "truth_bridge"),
        ("v2", "bridge_v2_red_20261020.jsonl", "v2_red_planning_runs.csv", "truth_bridge")]:
        data, stages = planner_dir / "evidence" / data_name, planner_dir / "evidence" / csv_name
        source_paths.update([data, stages])
        result = subprocess.run([sys.executable, "-B", str(script), str(data), str(stages), "--kind", kind],
                                cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        (evidence / ("planner_" + label + ".json")).write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stderr)
        planning.append({"configuration": label, **json.loads(result.stdout)})
    audit["historical_planning_reanalysis"] = planning
    cost_checks = []
    for label in ["v1", "v2"]:
        path = planner_dir / f"evidence/cost_{label}_red_20261020.log"
        source_paths.add(path)
        counts = [int(x) for x in re.findall(r"nonzero_evals=(\d+)", path.read_text(encoding="utf-8"))]
        cost_checks.append({"configuration": label, "logged_samples": len(counts),
                            "nonzero_samples": sum(x > 0 for x in counts), "counts": counts})
    audit["planning_cost_activation"] = cost_checks

    # Replay recorded answer candidates against the actual frozen selector.
    # These are fixed, previously prompted candidates, NOT new LLM performance trials.
    module = load_module(frozen / "model/mission_once.py")
    module.RETRY_BUDGET_S = 3600
    scoring_script = repo / "v3_stability/rule_compliance/tools/llm_paraphrase_probe.py"
    source_paths.add(scoring_script)
    score = runpy.run_path(str(scoring_script), run_name="offline_score")["score"]
    dataset_summaries, replay_rows = [], []
    for dataset in sorted((repo / "v3_stability/reports").glob("rule_compliance*/**/samples.jsonl")):
        source_paths.add(dataset)
        records = [json.loads(line) for line in dataset.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        selected_rows = []
        for record in records:
            answers = [item.get("extracted_commands") for item in record.get("raw_answers", [])]
            if not answers or not isinstance(record.get("expected_commands"), list):
                continue
            remaining = list(answers[:3])
            module.MAX_ATTEMPTS = len(remaining)
            module.generate_commands = lambda *unused: remaining.pop(0)
            messages = io.StringIO()
            with contextlib.redirect_stdout(messages):
                selected = module.generate_validated_commands(None, None, [], record["prompt"])
            normalize = lambda value: [s.strip() for s in (value or "").splitlines() if s.strip()]
            row = {"dataset": dataset.relative_to(repo).as_posix(), "case_id": record.get("case_id"),
                   "repetition": record.get("repetition"), "prompt": record["prompt"],
                   "candidate_count": len(answers), "expected": record["expected_commands"],
                   "first_candidate": answers[0], "recorded_final": record.get("final_commands"),
                   "replayed_final": selected,
                   "first_exact": normalize(answers[0]) == record["expected_commands"],
                   "recorded_exact": normalize(record.get("final_commands")) == record["expected_commands"],
                   "replayed_exact": normalize(selected) == record["expected_commands"],
                   "recorded_passed_flag": record.get("passed"),
                   "first_strict": not score(answers[0], record["raw_answers"][:1], record["expected_commands"]),
                   "recorded_strict": not score(record.get("final_commands"), record["raw_answers"], record["expected_commands"]),
                   "replayed_strict": not score(selected, record["raw_answers"], record["expected_commands"]),
                   "replayed_failure_classes": score(selected, record["raw_answers"], record["expected_commands"]),
                   "selection_changed": selected != record.get("final_commands"),
                   "all_recorded_candidates": answers,
                   "recorded_module_md5": record.get("tested_module_md5"), "replay_trace": messages.getvalue()}
            replay_rows.append(row)
            selected_rows.append(row)
        dataset_summaries.append({"dataset": dataset.relative_to(repo).as_posix(), "total_records": len(records),
            "n": len(selected_rows), "excluded_records": len(records) - len(selected_rows),
            **{key: sum(r[key] for r in selected_rows) for key in ["first_exact", "recorded_exact", "replayed_exact",
                                                               "first_strict", "recorded_strict", "replayed_strict", "selection_changed"]},
            "recorded_score_mismatches": sum(r["recorded_strict"] != r["recorded_passed_flag"] for r in selected_rows)})
    audit["fixed_candidate_replay"] = dataset_summaries
    write_json(evidence / "recorded_candidate_replay.json", replay_rows)

    # Check the semantics of the stored setpoint metric, without relabeling it as path length.
    metrics = repo / "v3_stability/reports/hit_balloon_part1_1.6/return_setpoint_control_vs_patch.jsonl"
    source_paths.add(metrics)
    audit["stored_return_setpoint_metrics"] = [json.loads(x) for x in metrics.read_text(encoding="utf-8").splitlines() if x.strip()]
    final_csv = repo / "v3_stability/reports/hit_balloon_part1_1.8/evidence/batch5_gc_summary.csv"
    source_paths.add(final_csv)
    with final_csv.open(encoding="utf-8-sig", newline="") as f:
        final_rows = list(csv.DictReader(f))
    audit["historical_final_nine_trials"] = {
        "trials": len(final_rows), "started_with_three": sum(int(r["before_count"]) == 3 for r in final_rows),
        "ended_with_two": sum(int(r["settled_count"]) == 2 for r in final_rows),
        "observer_mission_success": sum(r["mission_success"].lower() == "true" for r in final_rows),
        "boundary_events": sum(int(r["boundary_violations"]) for r in final_rows),
        "trials_with_boundary": sum(int(r["boundary_violations"]) > 0 for r in final_rows),
        "gc_samples": sum(int(r["gc_samples"]) for r in final_rows),
        "gc_errors": sum(int(r["gc_errors"]) for r in final_rows),
        "scope": "CSV/Actor count reanalysis only; does not independently establish color identity or physical contact"}
    write_csv(evidence / "historical_final_nine_trials.csv", final_rows)
    write_json(evidence / "source_manifest.json", {p.relative_to(repo).as_posix(): hashes(p) for p in sorted(source_paths)})
    write_json(out / "results.json", audit)
    print(json.dumps({"commit": provenance.get("commit"),
                     "integrity_passed": sum(row["matches_manifest"] for row in checks),
                     "tests": tests, "timing": audit["historical_stage_timing"],
                     "replay": dataset_summaries,
                     "planner": [{"label": row["configuration"], "distance_m": row["balloon_stage_min"]["distance_m"],
                                  "n": row["balloon_stage_distance_samples"]} for row in planning]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
