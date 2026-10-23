#!/usr/bin/env python3
"""MD5-gated install or rollback of the balloon-clearance concept-test files.

The payload root has the same relative layout as ego-planner's repository root.
All original files are backed up before any replacement; the JSON manifest
records original and deployed hashes for an exact rollback.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


EXPECTED = {
    "src/planner/bspline_opt/src/bspline_optimizer.cpp": "a968a5e81b3799c2ed68d75b582f5fc4",
    "src/planner/bspline_opt/include/bspline_opt/bspline_optimizer.h": "2d2615f01a3834ac24104360e43426b6",
    "src/planner/bspline_opt/CMakeLists.txt": "0fc1056df778674f1571a427bab78562",
    "src/planner/bspline_opt/package.xml": "da5f06411d24160a919de5ba17d4c4f2",
}
BACKUP_SUFFIX = ".bak_20261020_balloon_v1"


def md5(data):
    return hashlib.md5(data).hexdigest()


def deploy(args):
    if args.manifest.exists():
        raise SystemExit(f"manifest already exists: {args.manifest}")
    files = []
    for relative, expected in EXPECTED.items():
        source = args.source_root / relative
        payload = args.payload_root / relative
        backup = source.with_name(source.name + BACKUP_SUFFIX)
        if not source.is_file() or not payload.is_file() or backup.exists():
            raise SystemExit(f"missing source/payload or backup exists: {relative}")
        original_data = source.read_bytes()
        target_data = payload.read_bytes()
        if md5(original_data) != expected or original_data == target_data:
            raise SystemExit(f"MD5 mismatch or no change: {relative}")
        files.append((relative, source, backup, original_data, target_data))
    for _, source, backup, original_data, _ in files:
        backup.write_bytes(original_data)
        shutil.copymode(source, backup)
    changed = []
    try:
        for relative, source, _, _, target_data in files:
            temp = source.with_name(source.name + ".balloon_v1.tmp")
            temp.write_bytes(target_data)
            shutil.copymode(source, temp)
            os.replace(temp, source)
            changed.append(relative)
    except Exception:
        for relative, source, backup, _, _ in files:
            if relative in changed:
                shutil.copy2(backup, source)
        raise
    manifest = {"files": [
        {"relative": relative, "original_md5": md5(original_data),
         "deployed_md5": md5(target_data), "backup": str(backup)}
        for relative, _, backup, original_data, target_data in files]}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest))


def rollback(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        source = args.source_root / entry["relative"]
        backup = Path(entry["backup"])
        if md5(source.read_bytes()) != entry["deployed_md5"]:
            raise SystemExit(f"deployed MD5 mismatch: {source}")
        if md5(backup.read_bytes()) != entry["original_md5"]:
            raise SystemExit(f"backup MD5 mismatch: {backup}")
    for entry in manifest["files"]:
        source = args.source_root / entry["relative"]
        shutil.copy2(entry["backup"], source)
        os.utime(source, None)  # force the original C++ code to be rebuilt
        print(f"restored {source}: {md5(source.read_bytes())}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        rollback(args)
    else:
        if args.payload_root is None:
            parser.error("--payload-root is required for deployment")
        deploy(args)


if __name__ == "__main__":
    main()
