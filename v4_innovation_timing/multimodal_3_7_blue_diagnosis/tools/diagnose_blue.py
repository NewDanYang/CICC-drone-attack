"""Create the offline blue failure audit from the 3.6 scored evidence."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E36 = Path(__file__).resolve().parents[2] / "multimodal_3_6_lora_v2" / "evidence"
OUT = ROOT / "evidence"

BLUE_REJECTS = {
    "run3_00031_blue": "bbox on tripod/ground; visible blue balloon elsewhere",
    "run3_00032_blue": "bbox on tripod/ground; visible blue balloon elsewhere",
    "run3_00033_blue": "bbox on tripod/ground; visible blue balloon elsewhere",
    "run3_00045_blue": "bbox on tripod/ground; no blue balloon inside box",
    "run7_00037_blue": "bbox on tripod/ground; visible blue balloon elsewhere",
    "run3_00008_blue": "purple balloon labeled blue",
    "run3_00009_blue": "purple balloon labeled blue",
    "run3_00010_blue": "purple balloon labeled blue",
    "run3_00011_blue": "purple balloon labeled blue",
    "run7_00007_blue": "severely occluded/loose box; not a tight visible-body box",
    "run7_00022_blue": "purple balloon labeled blue",
    "run7_00025_blue": "purple balloon labeled blue",
    "run7_00046_blue": "purple balloon labeled blue",
}


def main():
    cases = json.loads((E36 / "cases.json").read_text(encoding="utf-8"))
    scored = {r["id"]: r for r in json.loads((E36 / "eval_adapter_test_scored.json").read_text(encoding="utf-8"))}
    predictions = {}
    for line in (Path(".scratch/remote_mm36/diagnosis/predictions.jsonl")).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        predictions[row["id"]] = row

    failures = []
    for row in cases:
        if row["split"] != "test" or not row["present"] or row["color"] != "blue":
            continue
        s = scored[row["id"]]
        p = predictions[row["id"]]
        if row["id"] == "run7_00023_blue":
            mode = "test_label_color_confusion: purple balloon in blue row"
        elif row["id"] == "run7_00053_blue":
            mode = "malformed_bbox_output"
        elif s.get("center_error_px") is not None and abs((s["predicted_bbox_px"][0] + s["predicted_bbox_px"][2]) / 2 - (row["bbox"][0] + row["bbox"][2]) / 2) >= 12:
            mode = "bbox_center_offset"
        else:
            mode = "bbox_scale_or_small_target"
        failures.append(
            {
                "id": row["id"],
                "true_bbox_px": row["bbox"],
                "predicted_bbox_px": s.get("predicted_bbox_px"),
                "iou": s["iou"],
                "center_error_px": s["center_error_px"],
                "threshold_px": s.get("center_error_threshold_px"),
                "geometry_pass": s["geometry_pass"],
                "true_region": row["region"],
                "predicted_region": json.loads(p["region"]["answer"]),
                "predicted_bbox_answer": p["bbox"]["answer"],
                "speed_mps": row["speed"],
                "target_max_edge_px": max(row["bbox"][2] - row["bbox"][0], row["bbox"][3] - row["bbox"][1]),
                "failure_mode": mode,
            }
        )

    train_blue = [r for r in cases if r["split"] == "train" and r["present"] and r["color"] == "blue"]
    kept = [r for r in train_blue if r["id"] not in BLUE_REJECTS]
    audit = {
        "test_blue": {
            "n": len(failures),
            "nonempty_bbox_outputs": sum(x["predicted_bbox_px"] is not None for x in failures),
            "malformed_or_empty_outputs": sum(x["predicted_bbox_px"] is None for x in failures),
            "geometry_hits": sum(x["geometry_pass"] for x in failures),
            "median_center_error_px": statistics.median([x["center_error_px"] for x in failures if x["center_error_px"] is not None]),
            "median_target_max_edge_px": statistics.median(x["target_max_edge_px"] for x in failures),
            "failures": failures,
        },
        "train_blue_quality": {
            "raw_n": len(train_blue),
            "rejected_n": len(BLUE_REJECTS),
            "kept_n": len(kept),
            "rejected": BLUE_REJECTS,
            "kept_max_edge_px_median": statistics.median(max(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]) for r in kept),
            "kept_max_edge_px_max": max(max(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]) for r in kept),
        },
        "root_cause": {
            "primary": "data_quality_and_task_scale",
            "evidence": [
                "13/37 training blue rows are visibly mislabeled, on the tripod/ground, or too occluded/loose to be reliable tight boxes",
                "run7_00023_blue in the test set is visibly a purple balloon",
                "the 24 retained clean blue training boxes all have max edge <=30 px, leaving no clean medium/large blue scale coverage",
                "the nine parseable blue test predictions are mostly nonempty but have median center offset about 12 px right and 10 px down",
            ],
            "not_supported": "A pure physical-color impossibility explanation is not supported: most test blue crops show a visible high-contrast blue balloon; the failure is dominated by label contamination, tiny targets, and coordinate sensitivity.",
        },
    }
    (OUT / "blue_diagnosis.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
