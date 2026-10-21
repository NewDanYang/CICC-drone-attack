#!/usr/bin/env python3
"""MD5-gated candidate 3: change only Ego-Planner's max_vel launch arg."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


EXPECTED_A0_MD5 = ""
MARKER = "time_opt_candidate3"


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/home/ubuntu/catkin_ws/src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch"))
    parser.add_argument("--manifest", type=Path, default=Path("/home/ubuntu/tcei_baseline_tools/time_optimization/candidate3_manifest.json"))
    parser.add_argument("--value", type=float, default=0.40)
    parser.add_argument("--expected-md5", default=EXPECTED_A0_MD5)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    backup = args.source.with_name(args.source.name + ".bak_" + MARKER)
    if args.rollback:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if digest(args.source) != manifest["after_md5"] or digest(backup) != manifest["before_md5"]:
            raise SystemExit("MD5 mismatch; refusing candidate 3 rollback")
        shutil.copy2(backup, args.source)
        print(json.dumps({"rolled_back": str(args.source), "md5": digest(args.source)}))
        return
    if not 0.35 <= args.value <= 0.50:
        raise SystemExit("candidate 3 value must be one of the approved A1..A4 values")
    if not args.expected_md5:
        raise SystemExit("pass the measured official A0 launch MD5 before deploying")
    if args.manifest.exists() or backup.exists():
        raise SystemExit("candidate 3 manifest or backup already exists")
    before = args.source.read_bytes()
    if hashlib.md5(before).hexdigest() != args.expected_md5.lower():
        raise SystemExit("source MD5 differs from the measured official A0 launch")
    text = before.decode("utf-8")
    old = '<arg name="max_vel" value="0.3" />'
    new = f'<arg name="max_vel" value="{args.value:g}" />'
    if text.count(old) != 1:
        raise SystemExit("official max_vel anchor is not unique")
    after = text.replace(old, new).encode("utf-8")
    shutil.copy2(args.source, backup)
    temp = args.source.with_name(args.source.name + ".tmp")
    temp.write_bytes(after)
    shutil.copymode(args.source, temp)
    temp.replace(args.source)
    record = {
        "candidate": 3,
        "max_vel": args.value,
        "source": str(args.source),
        "before_md5": hashlib.md5(before).hexdigest(),
        "after_md5": hashlib.md5(after).hexdigest(),
        "backup": str(backup),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
