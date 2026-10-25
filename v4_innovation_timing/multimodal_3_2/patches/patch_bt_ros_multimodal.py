#!/usr/bin/env python3
"""Patch only the generated balloon tracker node.

The live source is guarded by an explicit MD5 supplied by the deployment
wrapper.  The patch leaves VisualServo, safety parameters and all other stages
untouched.  It is byte-preserving apart from the one XML node name.
"""
import argparse
import hashlib
import pathlib
import shutil

OLD = b'<TargetTracker object_name="'  # checked together with the full line
OLD_LINE = b'            "            <TargetTracker object_name=\\\"" + balloon_name + "\\\" "'
NEW_LINE = b'            "            <MultimodalTargetTracker object_name=\\\"" + balloon_name + "\\\" "'


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=pathlib.Path)
    ap.add_argument("output", type=pathlib.Path)
    ap.add_argument("--expected-md5", required=True)
    ap.add_argument("--backup-dir", type=pathlib.Path)
    args = ap.parse_args()
    actual = md5(args.source)
    if actual != args.expected_md5.lower():
        raise SystemExit(f"MD5 mismatch: expected {args.expected_md5}, got {actual}")
    raw = args.source.read_bytes()
    if raw.count(OLD_LINE) != 1:
        raise SystemExit(f"expected one balloon TargetTracker line, found {raw.count(OLD_LINE)}")
    patched = raw.replace(OLD_LINE, NEW_LINE)
    if patched == raw or patched.count(b"MultimodalTargetTracker") != 1:
        raise SystemExit("patch did not change exactly one node")
    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.source, args.backup_dir / args.source.name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"before_md5={actual}")
    print(f"after_md5={md5(args.output)}")


if __name__ == "__main__":
    main()
