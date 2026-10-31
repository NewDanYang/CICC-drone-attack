"""Audit the frozen 3.6 dataset/training/evaluation evidence.

This script only reads archived evidence.  It does not load the model, query
ROS, or change the formal scoring rules from the 3.5 report.
"""
from __future__ import annotations

import collections
import hashlib
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
COLORS = ("red", "purple", "blue")


def read(name: str):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def size_bin(row):
    if not row.get("present") or not row.get("bbox"):
        return "negative"
    x0, y0, x1, y1 = row["bbox"]
    edge = max(x1 - x0, y1 - y0)
    return "small" if edge <= 40 else "medium" if edge <= 80 else "large"


def group_metrics(rows):
    pos = [r for r in rows if r["present"]]
    neg = [r for r in rows if not r["present"]]
    return {
        "n": len(rows),
        "positive": len(pos),
        "negative": len(neg),
        "region_hits": sum(bool(r["region_correct"]) for r in pos),
        "geometry_hits": sum(bool(r["geometry_pass"]) for r in pos),
        "pipeline_geometry_hits": sum(bool(r["pipeline_geometry_pass"]) for r in pos),
        "region_negative_errors": sum(not r["region_correct"] for r in neg),
        "bbox_negative_errors": sum(r["bbox_nonempty"] or not r["bbox_valid"] for r in neg),
    }


def prior_breakers(cases, scored):
    modes = {}
    for color in COLORS:
        counts = collections.Counter(
            r["region"]
            for r in cases
            if r["split"] == "train" and r["present"] and r["color"] == color
        )
        modes[color] = counts.most_common(1)[0][0]
    by_id = {r["id"]: r for r in scored}
    out = {"train_modal_region": modes, "colors": {}}
    for color in COLORS:
        candidates = [
            r
            for r in cases
            if r["split"] == "test"
            and r["present"]
            and r["color"] == color
            and r["region"] != modes[color]
        ]
        evaluated = [by_id[r["id"]] for r in candidates]
        out["colors"][color] = {
            "n": len(evaluated),
            "region_hits": sum(r["region_correct"] for r in evaluated),
            "pipeline_geometry_hits": sum(r["pipeline_geometry_pass"] for r in evaluated),
            "ids": [r["id"] for r in candidates],
        }
    return out


def main():
    cases = read("cases.json")
    adapter_test = read("eval_adapter_test_scored.json")
    adapter_val = read("eval_adapter_validation_scored.json")
    base_test = read("eval_base_test_summary.json")
    base_val = read("eval_base_validation_summary.json")

    by_hash = collections.defaultdict(set)
    for row in cases:
        by_hash[row["sha256"]].add(row["split"])
    by_run = collections.defaultdict(set)
    for row in cases:
        by_run[row["run"]].add(row["split"])

    dataset = {}
    for split in ("train", "validation", "test"):
        rows = [r for r in cases if r["split"] == split]
        pos = [r for r in rows if r["present"]]
        dataset[split] = {
            "rows": len(rows),
            "images": len({r["sha256"] for r in rows}),
            "positive_by_color": {
                c: sum(r["present"] and r["color"] == c for r in rows) for c in COLORS
            },
            "region_by_color": {
                c: dict(collections.Counter(r["region"] for r in pos if r["color"] == c))
                for c in COLORS
            },
            "size_bins": dict(collections.Counter(size_bin(r) for r in pos)),
            "clipped_positive": sum(r["clipped"] for r in pos),
            "speed_median_mps": statistics.median(r["speed"] for r in pos) if pos else None,
            "speed_max_mps": max((r["speed"] for r in pos), default=None),
            "speed_over_0_35_mps": sum(r["speed"] > 0.35 for r in pos),
            "runs": dict(collections.Counter(r["run"] for r in rows)),
        }

    training_state = read("trainer_state.json")
    eval_curve = [
        {"step": x["step"], "eval_loss": x["eval_loss"]}
        for x in training_state.get("log_history", [])
        if "eval_loss" in x
    ]
    analysis = {
        "dataset": dataset,
        "sha256_cross_split_count": sum(len(v) > 1 for v in by_hash.values()),
        "run_to_splits": {k: sorted(v) for k, v in sorted(by_run.items())},
        "adapter_test": group_metrics(adapter_test),
        "adapter_validation": group_metrics(adapter_val),
        "base_test_summary": base_test,
        "base_validation_summary": base_val,
        "prior_breakers": prior_breakers(cases, adapter_test),
        "training": {
            "global_step": training_state.get("global_step"),
            "best_metric": training_state.get("best_metric"),
            "best_model_checkpoint": training_state.get("best_model_checkpoint"),
            "eval_curve": eval_curve,
        },
        "evidence_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(EVIDENCE.iterdir())
            if p.is_file() and p.name not in {"analysis.json"}
        },
    }
    (EVIDENCE / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
