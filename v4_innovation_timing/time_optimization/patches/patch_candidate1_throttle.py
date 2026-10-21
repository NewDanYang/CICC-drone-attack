#!/usr/bin/env python3
"""MD5-gated candidate 1: shorten only the Takeoff request retry interval."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


EXPECTED_MD5 = "7334b435faceae983f46f3dd185da172"
MARKER = "time_opt_candidate1"


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/home/ubuntu/catkin_ws/src/mission_pkg/include/base/drone_action_node.h"))
    parser.add_argument("--manifest", type=Path, default=Path("/home/ubuntu/tcei_baseline_tools/time_optimization/candidate1_manifest.json"))
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    backup = args.source.with_name(args.source.name + ".bak_" + MARKER)

    if args.rollback:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if md5(args.source) != manifest["after_md5"] or md5(backup) != manifest["before_md5"]:
            raise SystemExit("MD5 mismatch; refusing candidate 1 rollback")
        shutil.copy2(backup, args.source)
        print(json.dumps({"rolled_back": str(args.source), "md5": md5(args.source)}))
        return

    if not 1.0 <= args.interval <= 3.0:
        raise SystemExit("interval must be within the pre-approved 1.0..3.0 s range")
    if args.manifest.exists() or backup.exists():
        raise SystemExit("candidate 1 manifest or backup already exists")
    before = args.source.read_bytes()
    if hashlib.md5(before).hexdigest() != EXPECTED_MD5:
        raise SystemExit("source MD5 differs from the pristine candidate 1 input")
    text = before.decode("utf-8")
    old_mode = "bool throttledSetMode(const std::string& mode, double interval_sec = 5.0);"
    old_arm = "bool throttledArm(bool value, double interval_sec = 5.0);"
    new_mode = f"bool throttledSetMode(const std::string& mode, double interval_sec = {args.interval:.1f});"
    new_arm = f"bool throttledArm(bool value, double interval_sec = {args.interval:.1f});"
    if text.count(old_mode) != 1 or text.count(old_arm) != 1:
        raise SystemExit("expected candidate 1 declarations are not unique")
    after = text.replace(old_mode, new_mode).replace(old_arm, new_arm).encode("utf-8")
    shutil.copy2(args.source, backup)
    temp = args.source.with_name(args.source.name + ".tmp")
    temp.write_bytes(after)
    shutil.copymode(args.source, temp)
    temp.replace(args.source)
    record = {
        "candidate": 1,
        "source": str(args.source),
        "interval_s": args.interval,
        "before_md5": hashlib.md5(before).hexdigest(),
        "after_md5": hashlib.md5(after).hexdigest(),
        "backup": str(backup),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
