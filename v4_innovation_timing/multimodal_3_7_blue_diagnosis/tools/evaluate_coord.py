"""Offline evaluator for the coordinate-only 3.7 adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import time
from pathlib import Path


COLORS = {"red": "红色", "purple": "紫色", "blue": "蓝色"}


def prompt(color: str) -> str:
    cn = COLORS[color]
    return (
        f"请定位这张图片中实际可见的{cn}气球球体，排除小车、绳子、墙面。"
        "只输出一个JSON对象，只有bbox字段。bbox是气球可见部分的紧致矩形，"
        "格式为[x_min,y_min,x_max,y_max]，以当前这张图片的左上角为(0,0)、右下角为(1000,1000)，"
        "四个坐标均为0到1000之间的整数，x向右增加，y向下增加。"
        f"没有实际可见{cn}气球时输出{{\"bbox\":null}}。不要解释，不要Markdown。"
    )


def strict_json(text: str):
    text = text.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    return json.loads(text)


def score(prediction: str, label: dict) -> dict:
    out = {
        "id": label["id"],
        "color": label["color"],
        "present": label["present"],
        "clipped": label["clipped"],
        "bbox_valid": False,
        "bbox_nonempty": False,
        "geometry_pass": False,
        "iou": 0.0,
        "center_error_px": None,
    }
    try:
        obj = strict_json(prediction)
        assert isinstance(obj, dict) and set(obj) == {"bbox"}
        box = obj["bbox"]
        if box is None:
            out["bbox_valid"] = True
        else:
            assert isinstance(box, list) and len(box) == 4 and all(type(v) is int for v in box)
            assert 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000
            px = [box[i] * (640 / 1000 if i % 2 == 0 else 480 / 1000) for i in range(4)]
            out.update(bbox_valid=True, bbox_nonempty=True, predicted_bbox_px=px)
            if label["bbox"]:
                a, b, c, d = px
                x, y, z, w = label["bbox"]
                inter = max(0, min(c, z) - max(a, x)) * max(0, min(d, w) - max(b, y))
                iou = inter / ((c - a) * (d - b) + (z - x) * (w - y) - inter)
                error = math.hypot((a + c - x - z) / 2, (b + d - y - w) / 2)
                threshold = max(8, 0.2 * math.hypot(z - x, w - y))
                out.update(
                    iou=iou,
                    center_error_px=error,
                    center_error_threshold_px=threshold,
                    geometry_pass=iou >= 0.5 and error <= threshold,
                )
    except (ValueError, KeyError, AssertionError, TypeError, json.JSONDecodeError):
        out["bbox_parse_error"] = True
    return out


def group(rows):
    pos = [r for r in rows if r["present"]]
    neg = [r for r in rows if not r["present"]]
    return {
        "n": len(rows),
        "positive": len(pos),
        "negative": len(neg),
        "geometry_hits": sum(r["geometry_pass"] for r in pos),
        "bbox_negative_errors": sum(r["bbox_nonempty"] or not r["bbox_valid"] for r in neg),
        "median_center_error_px": statistics.median(
            [r["center_error_px"] for r in pos if r["center_error_px"] is not None]
        ) if any(r["center_error_px"] is not None for r in pos) else None,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--split", choices=["validation", "test"], required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--adapter", type=Path)
    p.add_argument("--model", default="/home/ubuntu/model/FM9G4B-V")
    a = p.parse_args()
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
    model = AutoModel.from_pretrained(a.model, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(a.adapter), is_trainable=False)
    model = model.cuda().to(dtype=torch.bfloat16).eval()
    rows = [r for r in json.loads((a.data / "cases.json").read_text()) if r["split"] == a.split]
    a.output.mkdir(parents=True)
    (a.output / "config.json").write_text(json.dumps({"model": a.model, "adapter": str(a.adapter), "split": a.split,
        "cases_sha256": hashlib.sha256((a.data / "cases.json").read_bytes()).hexdigest(),
        "coordinate_only": True, "max_new_tokens": 128, "sampling": False}, indent=2) + "\n")
    predictions = []
    with (a.output / "predictions.jsonl").open("w", encoding="utf-8", buffering=1) as stream:
        for i, row in enumerate(rows, 1):
            image = Image.open(row["image_path"]).convert("RGB")
            start = time.perf_counter()
            with torch.inference_mode():
                answer = model.chat(image=None, msgs=[{"role": "user", "content": [image, prompt(row["color"])]}],
                    tokenizer=tok, processor=proc, sampling=False, stream=False, num_beams=1, max_new_tokens=128)
            result = dict(row, prediction=answer, latency_s=time.perf_counter() - start)
            predictions.append(result)
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"{i}/{len(rows)} {row['id']}", flush=True)
    scored = [score(r["prediction"], r) for r in predictions]
    (a.output / "scored.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n")
    summary = {"overall": group(scored), "colors": {c: group([r for r in scored if r["color"] == c]) for c in COLORS},
               "clipped": group([r for r in scored if r["clipped"]]),
               "unclipped": group([r for r in scored if not r["clipped"]]),
               "median_call_latency_s": statistics.median([r["latency_s"] for r in predictions]) if predictions else None,
               "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
               "peak_reserved_bytes": torch.cuda.max_memory_reserved()}
    (a.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
