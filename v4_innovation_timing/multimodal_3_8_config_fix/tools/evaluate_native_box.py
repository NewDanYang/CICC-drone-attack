#!/usr/bin/env python3
"""Zero-shot evaluation using FM9G4B-V's native <box> format."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from pathlib import Path

COLORS = {"red": "红色", "purple": "紫色", "blue": "蓝色"}
BOX_RE = re.compile(r"<box>\s*([0-9]{1,4})\s*[, ]\s*([0-9]{1,4})\s*[, ]\s*([0-9]{1,4})\s*[, ]\s*([0-9]{1,4})\s*</box>", re.I)
NULL_RE = re.compile(r"<box>\s*(?:none|null|不可见|)\s*</box>", re.I)


def prompt(color: str) -> str:
    cn = COLORS[color]
    return (
        f"请定位图片中实际可见的{cn}气球球体，排除小车、绳子和墙面。"
        "只使用模型原生格式输出：<box>x1 y1 x2 y2</box>，四个坐标归一化到0到1000，"
        "x向右增加、y向下增加；没有实际可见目标时输出<box>None</box>。不要解释，不要Markdown。"
    )


def parse_native(text: str):
    text = str(text).strip()
    if NULL_RE.search(text):
        return None, True
    m = BOX_RE.search(text)
    if not m:
        raise ValueError("no native box")
    vals = [int(x) for x in m.groups()]
    if not (0 <= vals[0] < vals[2] <= 1000 and 0 <= vals[1] < vals[3] <= 1000):
        raise ValueError("invalid native box")
    return vals, True


def score(prediction: str, label: dict) -> dict:
    out = {"id": label["id"], "color": label["color"], "present": label["present"],
           "clipped": label["clipped"], "bbox_valid": False, "bbox_nonempty": False,
           "geometry_pass": False, "iou": 0.0, "center_error_px": None}
    try:
        box, valid = parse_native(prediction)
        out["bbox_valid"] = valid
        if box is None:
            return out
        px = [box[i] * (640 / 1000 if i % 2 == 0 else 480 / 1000) for i in range(4)]
        out.update(bbox_nonempty=True, predicted_bbox_px=px)
        if label["bbox"]:
            a, b, c, d = px
            x, y, z, w = label["bbox"]
            inter = max(0, min(c, z) - max(a, x)) * max(0, min(d, w) - max(b, y))
            union = (c - a) * (d - b) + (z - x) * (w - y) - inter
            iou = inter / union if union else 0.0
            error = math.hypot((a + c - x - z) / 2, (b + d - y - w) / 2)
            threshold = max(8, 0.2 * math.hypot(z - x, w - y))
            out.update(iou=iou, center_error_px=error,
                       center_error_threshold_px=threshold,
                       geometry_pass=iou >= 0.5 and error <= threshold)
    except (ValueError, TypeError, AssertionError):
        out["bbox_parse_error"] = True
    return out


def group(rows):
    pos = [r for r in rows if r["present"]]
    neg = [r for r in rows if not r["present"]]
    errors = [r["center_error_px"] for r in pos if r["center_error_px"] is not None]
    return {"n": len(rows), "positive": len(pos), "negative": len(neg),
            "geometry_hits": sum(r["geometry_pass"] for r in pos),
            "bbox_negative_errors": sum(r["bbox_nonempty"] or not r["bbox_valid"] for r in neg),
            "median_center_error_px": statistics.median(errors) if errors else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--split", choices=["validation", "test", "selfcheck"], required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--model", default="/home/ubuntu/model/FM9G4B-V")
    ap.add_argument("--adapter", type=Path)
    a = ap.parse_args()
    if a.output.exists():
        raise RuntimeError("Refusing to overwrite evaluation")
    if Path("/tmp/tcei_formal_trial.lock").exists():
        raise RuntimeError("Formal trial active")

    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor, AutoTokenizer

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True, local_files_only=True)
    proc = AutoProcessor.from_pretrained(a.model, trust_remote_code=True, local_files_only=True)
    model = AutoModel.from_pretrained(a.model, trust_remote_code=True, local_files_only=True,
                                      torch_dtype=torch.bfloat16)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(a.adapter), is_trainable=False)
    model = model.cuda().to(dtype=torch.bfloat16).eval()
    rows = [r for r in json.loads((a.data / "cases.json").read_text(encoding="utf-8")) if r["split"] == a.split]
    a.output.mkdir(parents=True)
    (a.output / "config.json").write_text(json.dumps({
        "model": a.model, "adapter": str(a.adapter) if a.adapter else None,
        "format": "native_box", "split": a.split,
        "cases_sha256": hashlib.sha256((a.data / "cases.json").read_bytes()).hexdigest(),
        "max_new_tokens": 128, "sampling": False,
    }, indent=2) + "\n")
    predictions = []
    with (a.output / "predictions.jsonl").open("w", encoding="utf-8", buffering=1) as stream:
        for i, row in enumerate(rows, 1):
            image = Image.open(row["image_path"]).convert("RGB")
            start = time.perf_counter()
            with torch.inference_mode():
                answer = model.chat(image=None, msgs=[{"role": "user", "content": [image, prompt(row["color"])]}],
                                     tokenizer=tok, processor=proc, sampling=False, stream=False,
                                     num_beams=1, max_new_tokens=128)
            result = dict(row, prediction=answer, latency_s=time.perf_counter() - start)
            predictions.append(result)
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"{i}/{len(rows)} {row['id']}", flush=True)
    scored = [score(r["prediction"], r) for r in predictions]
    (a.output / "scored.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    summary = {"overall": group(scored),
               "colors": {c: group([r for r in scored if r["color"] == c]) for c in COLORS},
               "clipped": group([r for r in scored if r["clipped"]]),
               "unclipped": group([r for r in scored if not r["clipped"]]),
               "median_call_latency_s": statistics.median([r["latency_s"] for r in predictions]) if predictions else None,
               "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
               "peak_reserved_bytes": torch.cuda.max_memory_reserved()}
    (a.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
