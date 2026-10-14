#!/usr/bin/env python3
"""Probe the deployed mission model without publishing to /mission_command.

Run on the simulation server after formal trials have finished.  This imports
the live mission_once.py and calls its own load_model and validation function.
"""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import statistics
import time


STEPS = ("takeoff", "cross_frame", "detect_aruco", "return_cross_frame", "land")
COLORS = ("red", "purple", "blue")
FULL_RED = ("takeoff", "cross_frame", "detect_aruco", "return_cross_frame", "hit_balloon:red", "land")
FULL_PURPLE = FULL_RED[:4] + ("hit_balloon:purple", "land")

# Each case is sampled independently; the six single-step cases represent six
# separate inputs, not one prompt containing six sentences.
CASES = [
    ("full_red", "full", "飞机起飞，然后穿过框，识别二维码，再穿回框，击破红色气球，最后回到起点并降落。", FULL_RED),
    ("full_purple", "full", "起飞，穿越方框，读二维码，原路穿回方框，扎破紫色的气球，然后降落。", FULL_PURPLE),
    ("step_takeoff", "single_step", "现在起飞。", ("takeoff",)),
    ("step_cross", "single_step", "穿过前方的方框。", ("cross_frame",)),
    ("step_aruco", "single_step", "识别二维码。", ("detect_aruco",)),
    ("step_return", "single_step", "逆序穿回刚才的方框。", ("return_cross_frame",)),
    ("step_hit", "single_step", "击破红色气球。", ("hit_balloon:red",)),
    ("step_land", "single_step", "返回起点并降落。", ("land",)),
    ("red_short", "color_wording", "打红气球。", ("hit_balloon:red",)),
    ("red_de", "color_wording", "扎破红色的气球。", ("hit_balloon:red",)),
    ("red_yanse", "color_wording", "撞破红颜色的气球。", ("hit_balloon:red",)),
    ("purple_verb", "color_wording", "消灭紫色的气球。", ("hit_balloon:purple",)),
    ("blue_ball", "color_wording", "撞破蓝色球。", ("hit_balloon:blue",)),
    ("red_context", "color_wording", "去打击区，把红色的那个击破。", ("hit_balloon:red",)),
    ("area_a_only", "area_no_color", "去A区打击气球。", None),
    ("area_b_only", "area_no_color", "去上方的B打击区击破气球。", None),
    ("distractor_color", "distractor", "不要碰蓝色气球，扎破红色的气球。", ("hit_balloon:red",)),
    ("negative_takeoff", "distractor", "先别起飞，现在只识别二维码。", ("detect_aruco",)),
    ("english_blue", "english", "Hit the blue balloon.", ("hit_balloon:blue",)),
    ("mixed_purple", "english", "Take off, cross the frame, identify the ArUco marker, return through the frame, hit the purple balloon, then land.", FULL_PURPLE),
]


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct / 100.0
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def labeled_blocks(raw):
    return [m.strip() for m in re.findall(r"```command\s*\n(.*?)```", raw, re.DOTALL | re.IGNORECASE)]


def score(final, attempts, expected):
    if expected is None:
        return ["area_no_color"]
    failures = []
    if not final or not any(final.strip() in labeled_blocks(a["raw_answer"]) for a in attempts):
        failures.append("no_command_block")
    actual = [line.strip() for line in (final or "").splitlines() if line.strip()]
    if any(line not in STEPS and line not in ["hit_balloon:" + c for c in COLORS] for line in actual):
        failures.append("unknown_command")
    wanted_colors = [line for line in expected if line.startswith("hit_balloon:")]
    actual_colors = [line for line in actual if line.startswith("hit_balloon:")]
    if wanted_colors and actual_colors and actual_colors != wanted_colors:
        failures.append("wrong_color")
    if not wanted_colors and actual_colors:
        failures.append("extra_color")
    if actual != list(expected):
        missing = list((Counter(expected) - Counter(actual)).elements())
        extra = list((Counter(actual) - Counter(expected)).elements())
        failures.append("steps_missing_or_extra" if missing or extra else "steps_wrong_order")
    return list(dict.fromkeys(failures))


def load_deployed(path):
    spec = importlib.util.spec_from_file_location("deployed_mission_once", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", default="/home/ubuntu/model/mission_once.py")
    parser.add_argument("--resource-dir", help="directory containing prompts/ and FM9G4B-V/ when probing a staged copy")
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--list-cases", action="store_true")
    args = parser.parse_args()
    if args.list_cases:
        for case in CASES:
            print(case[0], case[1], case[2])
        return
    if args.samples < 3:
        parser.error("at least three samples per case are required")
    import rospy
    rospy.init_node("rule_compliance_paraphrase_probe", anonymous=True, disable_signals=True)
    path = Path(args.module)
    module_md5 = hashlib.md5(path.read_bytes()).hexdigest()
    module = load_deployed(path)
    if args.resource_dir:
        module.__file__ = str(Path(args.resource_dir) / "mission_once.py")
    model, tokenizer, base_msgs = module.load_model()
    original_generate = module.generate_commands
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with (output / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for case_id, category, prompt, expected in CASES:
            for repetition in range(1, args.samples + 1):
                attempts = []

                def capture(*call_args, **call_kwargs):
                    raw = io.StringIO()
                    with redirect_stdout(raw):
                        commands = original_generate(*call_args, **call_kwargs)
                    attempts.append({"raw_answer": raw.getvalue().rstrip("\n"), "extracted_commands": commands})
                    return commands

                module.generate_commands = capture
                validation_log = io.StringIO()
                started = time.perf_counter()
                error = None
                try:
                    with redirect_stdout(validation_log):
                        final = module.generate_validated_commands(model, tokenizer, base_msgs, prompt)
                except Exception as exc:
                    final = None
                    error = repr(exc)
                elapsed = time.perf_counter() - started
                failure_classes = score(final, attempts, expected)
                if error:
                    failure_classes.append("inference_error")
                record = {
                    "case_id": case_id, "category": category, "repetition": repetition,
                    "prompt": prompt, "expected_commands": expected,
                    "expected_balloon_color_by_tested_regex": module.expected_balloon_color(prompt),
                    "raw_answers": attempts, "validation_log": validation_log.getvalue(),
                    "final_commands": final, "final_balloon_colors": module.command_balloon_colors(final),
                    "passed": not failure_classes, "failure_classes": failure_classes,
                    "elapsed_s": round(elapsed, 3), "error": error,
                    "tested_module_md5": module_md5,
                }
                records.append(record)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"{case_id} {repetition}/{args.samples}: {record['passed']} {failure_classes} {elapsed:.2f}s", flush=True)
    evaluable = [r for r in records if r["category"] != "area_no_color"]
    passed = sum(r["passed"] for r in evaluable)
    counts = Counter(kind for record in records for kind in record["failure_classes"])
    summary = {
        "tested_module": str(path), "tested_module_md5": module_md5,
        "model_resource_dir": args.resource_dir or str(path.parent),
        "sample_count": len(records), "evaluable_count": len(evaluable),
        "passed_count": passed, "accuracy": passed / len(evaluable),
        "meets_95_percent": passed / len(evaluable) >= 0.95,
        "failure_class_counts": dict(counts),
        "latency_p50_s": percentile([r["elapsed_s"] for r in records], 50),
        "latency_p95_s": percentile([r["elapsed_s"] for r in records], 95),
        "latency_definition": "wall time for generate_validated_commands, including retries",
        "accuracy_definition": "exact ordered command sequence, valid labeled command block, valid command names and target color; area-only cases excluded",
    }
    (output / "overall.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "category", "samples", "passed", "accuracy", "p50_s", "p95_s", "failure_classes"])
        writer.writeheader()
        for case_id, category, _, _ in CASES:
            rows = [r for r in records if r["case_id"] == case_id]
            writer.writerow({
                "case_id": case_id, "category": category, "samples": len(rows),
                "passed": sum(r["passed"] for r in rows),
                "accuracy": "design_unresolved" if category == "area_no_color" else sum(r["passed"] for r in rows) / len(rows),
                "p50_s": percentile([r["elapsed_s"] for r in rows], 50),
                "p95_s": percentile([r["elapsed_s"] for r in rows], 95),
                "failure_classes": json.dumps(dict(Counter(kind for r in rows for kind in r["failure_classes"])), ensure_ascii=False),
            })
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
