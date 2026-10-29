#!/usr/bin/env python3
"""Build a fixed, high-quality 20-positive-sample overfit self-check set."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).resolve().parents[2] / "multimodal_3_7_blue_diagnosis" / "dataset" / "cases.json"
COLORS = {"red": "red", "purple": "purple", "blue": "blue"}


def prompt(color: str) -> str:
    return (
        f"Locate the visible {COLORS[color]} balloon in this image. "
        "Output only the native format <box>x1 y1 x2 y2</box>, with integer coordinates normalized to 0-1000, "
        "where x increases right and y increases down. If the target is not visible, output <box>None</box>."
    )


def answer(row: dict) -> str:
    b = row["bbox"]
    vals = [round(v * (1000 / 640 if i % 2 == 0 else 1000 / 480)) for i, v in enumerate(b)]
    return f"<box>{vals[0]} {vals[1]} {vals[2]} {vals[3]}</box>"


def main():
    rows = json.loads(SOURCE.read_text(encoding="utf-8"))
    selected = []
    # Larger, unambiguous boxes for red/purple; all available clean blue boxes are small,
    # so choose the six largest clean blue examples.
    quotas = {"red": 7, "purple": 7, "blue": 6}
    used_images = set()
    for color, quota in quotas.items():
        pool = [r for r in rows if r["split"] == "train" and r["present"] and r["color"] == color]
        pool.sort(key=lambda r: max(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]), reverse=True)
        for row in pool:
            # Keep each self-check image unique. The source set contains frames
            # with multiple colors; duplicating a frame would test two answers
            # against one visual input and can create an avoidable ambiguity.
            if row["image"] in used_images:
                continue
            selected.append(row)
            used_images.add(row["image"])
            if sum(r["color"] == color for r in selected) == quota:
                break
    assert len(selected) == 20

    records = []
    for r in selected:
        records.append({
            "id": r["id"] + "_selfcheck_native",
            "image": "/root/gpufree-data/mm36_lora_v2/data/images/" + r["image"],
            "conversations": [
                {"role": "user", "content": prompt(r["color"])},
                {"role": "assistant", "content": answer(r)},
            ],
        })
    DATA = ROOT / "selfcheck20" / "data"
    DATA.mkdir(parents=True, exist_ok=True)
    manifest = []
    for r, rec in zip(selected, records):
        m = dict(r)
        m["id"] = rec["id"]
        m["image_path"] = rec["image"]
        m["split"] = "selfcheck"
        manifest.append(m)
    for name in ("train.json", "validation.json"):
        (DATA / name).write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DATA / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "task": "3.8 20-sample corrected-config overfit self-check",
        "n": len(records),
        "positive_by_color": {c: sum(r["color"] == c for r in selected) for c in quotas},
        "format": "native_box",
        "selected_ids": [r["id"] for r in records],
        "source_cases_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    (ROOT / "selfcheck20" / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
