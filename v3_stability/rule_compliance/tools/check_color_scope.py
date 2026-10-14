#!/usr/bin/env python3
"""Check color-enforcement scope in the exact staged mission module."""
import hashlib
import importlib.util
import json
from pathlib import Path

module_path = Path("/tmp/rule_compliance/mission_once.py")
spec = importlib.util.spec_from_file_location("rule_candidate", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cases = [
    ("去打A区的气球", None),
    ("别碰蓝色气球，扎破红色的气球", None),
    ("扎破红色的气球", "red"),
    ("hit the blue balloon", "blue"),
]
for prompt, expected in cases:
    actual = module.expected_balloon_color(prompt)
    row = {
        "module_md5": hashlib.md5(module_path.read_bytes()).hexdigest(),
        "prompt": prompt, "expected": expected, "actual": actual,
        "passed": actual == expected,
    }
    print(json.dumps(row, ensure_ascii=False))
    if not row["passed"]:
        raise SystemExit(1)
