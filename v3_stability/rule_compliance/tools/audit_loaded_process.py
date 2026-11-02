#!/usr/bin/env python3
"""Verify the executable and mapped release libraries of a live Linux process."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def file_record(path):
    with open(path, "rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if identity(before) != identity(after):
        raise RuntimeError("file changed during hashing: " + str(path))
    return {"sha256": digest.hexdigest(), "device": before.st_dev,
            "inode": before.st_ino, "size": before.st_size}


def audit(pid, executable, libraries):
    proc = Path("/proc") / str(pid)
    # starttime detects process exit/PID reuse during this audit.
    start = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
    maps = (proc / "maps").read_text()
    records = []
    expected = file_record(executable)
    actual = file_record(proc / "exe")
    records.append(dict(kind="executable", expected_path=str(executable),
                        proc_exe=os.readlink(proc / "exe"), expected=expected, actual=actual,
                        passed=actual == expected))
    for library in libraries:
        expected = file_record(library)
        matching = []
        for line in maps.splitlines():
            fields = line.split(None, 5)
            if len(fields) != 6:
                continue
            address, permissions, offset, device, inode, path = fields
            original_path = path[:-10] if path.endswith(" (deleted)") else path
            if original_path != str(library):
                continue
            major, minor = (int(part, 16) for part in device.split(":"))
            mapped_identity = (os.makedev(major, minor), int(inode))
            method = "proc_map_files"
            try:
                mapped = file_record(proc / "map_files" / address)
            except PermissionError:
                method = "mapped_device_inode_matched_open_file"
                mapped = file_record(library)
            passed = (not path.endswith(" (deleted)") and
                      mapped_identity == (mapped["device"], mapped["inode"]) and
                      mapped == expected)
            matching.append(dict(map=line, method=method, actual=mapped, passed=passed))
        records.append(dict(kind="mapped_library", expected_path=str(library),
                            expected=expected, mappings=matching,
                            passed=bool(matching) and all(x["passed"] for x in matching)))
    end = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
    return dict(schema_version=1, pid=pid, process_starttime=start,
                process_identity_unchanged=start == end, records=records,
                passed=start == end and all(x["passed"] for x in records),
                limit="Kernel mapped-file identity and file bytes; does not detect later memory modification or prove flight performance.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--library", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.pid, args.executable.resolve(), [p.resolve() for p in args.library])
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pid": args.pid, "passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
