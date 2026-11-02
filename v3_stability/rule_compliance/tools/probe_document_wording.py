#!/usr/bin/env python3
"""Check the authorized document stage phrases using real FM9G; publish no tasks."""
import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import time

CASES = (
    ("飞机起飞", "takeoff"), ("起飞", "takeoff"),
    ("穿过框", "cross_frame"), ("穿框", "cross_frame"),
    ("识别二维码", "detect_aruco"), ("再穿回框", "return_cross_frame"),
    ("去打击红色气球", "hit_balloon:red"), ("打击蓝色气球", "hit_balloon:blue"),
    ("刺破紫球", "hit_balloon:purple"), ("回到起点并降落", "land"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("at least three independent samples per phrase are required")
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("document_mission", args.module)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__file__ = str(args.resources / "mission_once.py")
    model, tokenizer, messages = module.load_model()
    original = module.generate_commands
    records = []
    with (args.output / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for phrase, expected in CASES:
            for repetition in range(args.samples):
                attempts = []

                def capture(*a, **kw):
                    raw = io.StringIO()
                    with redirect_stdout(raw):
                        command = original(*a, **kw)
                    attempts.append({"raw_answer": raw.getvalue(), "command": command})
                    return command

                module.generate_commands = capture
                validation = io.StringIO()
                start = time.monotonic()
                error = None
                final = None
                try:
                    with redirect_stdout(validation):
                        final = module.generate_validated_commands(model, tokenizer, messages, phrase)
                except Exception as exc:
                    error = repr(exc)
                row = dict(phrase=phrase, expected=expected, repetition=repetition + 1,
                           final=final, attempts=attempts, error=error,
                           validation=validation.getvalue(), seconds=time.monotonic() - start,
                           passed=error is None and final == expected and bool(attempts))
                records.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(json.dumps({k: row[k] for k in ("phrase", "repetition", "passed", "seconds")}, ensure_ascii=False), flush=True)
    summary = dict(scope="real FM9G language-only; no ROS commands published or flight",
                   module_sha256=hashlib.sha256(args.module.read_bytes()).hexdigest(),
                   prompt_sha256=hashlib.sha256((args.resources / "prompts/mission_prompt.txt").read_bytes()).hexdigest(),
                   samples=len(records), passed=sum(row["passed"] for row in records),
                   all_passed=all(row["passed"] for row in records))
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
