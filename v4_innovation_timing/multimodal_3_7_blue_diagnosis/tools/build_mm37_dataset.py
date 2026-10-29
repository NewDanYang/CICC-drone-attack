"""Build the coordinate-only 3.7 dataset from frozen evidence.

Train uses only run3 after removing the 13 manually identified blue-label
failures. Validation is run8 and test is run10, so no capture run is shared
between splits.  This script emits one bbox question per case and no region
questions.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
DATA = ROOT / "dataset"
COLORS = {"red": "红色", "purple": "紫色", "blue": "蓝色"}

# These are the samples manually rejected after inspecting the source frame:
# five boxes landed on the tripod/ground, four were purple balloons, and four
# were weak/occluded or purple/blue confusions.
BLUE_TRAIN_REJECTS = {
    "run3_00031_blue",
    "run3_00032_blue",
    "run3_00033_blue",
    "run3_00045_blue",
    "run7_00037_blue",
    "run3_00008_blue",
    "run3_00009_blue",
    "run3_00010_blue",
    "run3_00011_blue",
    "run7_00007_blue",
    "run7_00022_blue",
    "run7_00025_blue",
    "run7_00046_blue",
}


def bbox_prompt(color: str) -> str:
    cn = COLORS[color]
    return (
        f"请定位这张图片中实际可见的{cn}气球球体，排除小车、绳子、墙面。"
        "只输出一个JSON对象，只有bbox字段。bbox是气球可见部分的紧致矩形，"
        "格式为[x_min,y_min,x_max,y_max]，以当前这张图片的左上角为(0,0)、右下角为(1000,1000)，"
        "四个坐标均为0到1000之间的整数，x向右增加，y向下增加。"
        f"没有实际可见{cn}气球时输出{{\"bbox\":null}}。不要解释，不要Markdown。"
    )


def answer(row: dict) -> str:
    if row["bbox"] is None:
        box = None
    else:
        box = [
            round(v * (1000 / 640 if i % 2 == 0 else 1000 / 480))
            for i, v in enumerate(row["bbox"])
        ]
    return json.dumps({"bbox": box}, ensure_ascii=False, separators=(",", ":"))


def example(row: dict, image_root: str) -> dict:
    image = f"{image_root.rstrip('/')}/{row['image']}"
    return {
        "id": row["id"] + "_bbox",
        "image": image,
        "conversations": [
            {"role": "user", "content": bbox_prompt(row["color"])},
            {"role": "assistant", "content": answer(row)},
        ],
    }


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    old = json.loads((EVIDENCE / "cases.json").read_text(encoding="utf-8"))
    run8 = json.loads((EVIDENCE / "run8_final_cases.json").read_text(encoding="utf-8"))
    run10 = json.loads((EVIDENCE / "run10_final_cases.json").read_text(encoding="utf-8"))

    train = [
        dict(r, split="train", source_run=r["run"])
        for r in old
        if r["split"] == "train" and r["id"] not in BLUE_TRAIN_REJECTS
    ]
    validation = [dict(r, split="validation", source_run="run8") for r in run8]
    test = [dict(r, split="test", source_run="run10") for r in run10]

    # The remote image roots are intentionally explicit: the training and
    # evaluation commands run on the same server where these captures live.
    roots = {
        "train": "/root/gpufree-data/mm36_lora_v2/data/images",
        "validation": "/root/gpufree-data/mm36_data/run8",
        "test": "/root/gpufree-data/mm36_data/run10",
    }
    rows_by_split = {"train": train, "validation": validation, "test": test}
    for split, rows in rows_by_split.items():
        (DATA / f"{split}.json").write_text(
            json.dumps([example(r, roots[split]) for r in rows], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    manifest = []
    for split, rows in rows_by_split.items():
        for row in rows:
            manifest.append(
                dict(
                    row,
                    image_path=f"{roots[split].rstrip('/')}/{row['image']}",
                )
            )
    (DATA / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    all_rows = train + validation + test
    by_hash = collections.defaultdict(set)
    for r in all_rows:
        # New captures have no source SHA in the event manifest, so the run
        # identity remains the required independent grouping key here.
        if r.get("sha256"):
            by_hash[r["sha256"]].add(r["split"])
    receipt = {
        "task": "3.7 coordinate-only LoRA",
        "train_questions": len(train),
        "validation_questions": len(validation),
        "test_questions": len(test),
        "positive_by_split": {
            s: dict(collections.Counter(r["color"] for r in rows if r["present"]))
            for s, rows in rows_by_split.items()
        },
        "negative_by_split": {
            s: sum(not r["present"] for r in rows) for s, rows in rows_by_split.items()
        },
        "source_runs": {s: sorted({r["source_run"] for r in rows}) for s, rows in rows_by_split.items()},
        "cross_split_sha256_count": sum(len(v) > 1 for v in by_hash.values()),
        "region_questions": 0,
        "blue_train_rejected": sorted(BLUE_TRAIN_REJECTS),
        "files": {},
    }
    for p in sorted(DATA.glob("*.json")):
        receipt["files"][p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (DATA / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
