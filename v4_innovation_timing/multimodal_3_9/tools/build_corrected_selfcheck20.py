#!/usr/bin/env python3
"""Build a color-clean self-check set for the 3.9 hypothesis test."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).resolve().parents[2] / "multimodal_3_7_blue_diagnosis" / "dataset" / "cases.json"
OLD = Path(__file__).resolve().parents[2] / "multimodal_3_8_config_fix" / "selfcheck20" / "data" / "cases.json"


def prompt(color: str) -> str:
    return (
        f"Locate the visible {color} balloon in this image. "
        "Output only the native format <box>x1 y1 x2 y2</box>, with integer coordinates normalized to 0-1000, "
        "where x increases right and y increases down. If the target is not visible, output <box>None</box>."
    )


def answer(row):
    vals = [round(v * (1000 / 640 if i % 2 == 0 else 1000 / 480)) for i, v in enumerate(row["bbox"])]
    return f"<box>{vals[0]} {vals[1]} {vals[2]} {vals[3]}</box>"


def main():
    all_rows = json.loads(SOURCE.read_text(encoding="utf-8"))
    old_rows = json.loads(OLD.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in all_rows}
    # Preserve the seven red and six blue self-check examples. Replace the seven
    # visually red rows labelled purple with seven verified magenta/purple frames.
    keep_ids = [r["id"].replace("_selfcheck_native", "") for r in old_rows if r["color"] in ("red", "blue")]
    true_purple_ids = [
        "run3_00001_purple", "run3_00003_purple", "run3_00005_purple",
        "run3_00007_purple", "run3_00009_purple", "run3_00011_purple",
        "run3_00013_purple",
    ]
    selected = [by_id[x] for x in keep_ids + true_purple_ids]
    assert len(selected) == 20 and len({r["image"] for r in selected}) == 20

    records = []
    manifest = []
    for r in selected:
        rec = {
            "id": r["id"] + "_corrected_selfcheck",
            "image": "/root/gpufree-data/mm36_lora_v2/data/images/" + r["image"],
            "conversations": [
                {"role": "user", "content": prompt(r["color"])},
                {"role": "assistant", "content": answer(r)},
            ],
        }
        records.append(rec)
        m = dict(r)
        m["id"] = rec["id"]
        m["image_path"] = rec["image"]
        m["split"] = "corrected_selfcheck"
        manifest.append(m)
    data = ROOT / "corrected20" / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("train.json", "validation.json"):
        (data / name).write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (data / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "task": "3.9 color-clean self-check",
        "n": 20,
        "positive_by_color": {c: sum(r["color"] == c for r in selected) for c in ("red", "purple", "blue")},
        "format": "native_box",
        "replaced_color_contaminated_rows": [r["id"] for r in old_rows if r["color"] == "purple"],
        "verified_purple_ids": true_purple_ids,
        "source_cases_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    (ROOT / "corrected20" / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
