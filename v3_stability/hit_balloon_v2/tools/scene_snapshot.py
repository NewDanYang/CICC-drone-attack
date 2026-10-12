#!/usr/bin/env python3
"""Record the simulator's live balloon actor IDs without querying object payloads.

Run immediately before and after one locked formal trial, while no other trial
uses the shared simulator. The UE console output is kept verbatim in the JSONL
row so the actor set can be audited later. No flight control is sent.
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SDK = "/home/ubuntu/PX4PSP/RflySimAPIs/RflySimSDK/ue"
LOG = Path("/home/ubuntu/PX4PSP/RflySimUE5/RflySim3D/Saved/Logs/RflySim3D.log")
ACTOR = re.compile(r"BP_Balloon_C /\S*?(BP_Balloon_C_\d+)")
COUNT = re.compile(r"BP_Balloon_C\s+(\d+)\s+")
ZERO = re.compile(r"(?m)^.*\b0 Objects \(Total:")


def simulator_pid():
    result = subprocess.run(["pgrep", "-f", r"[.]\/RflySim3D$"],
                            text=True, capture_output=True, check=True)
    pids = result.stdout.split()
    if len(pids) != 1:
        raise RuntimeError(f"expected one RflySim3D process, found {pids}")
    return int(pids[0])


def snapshot():
    pid = simulator_pid()
    inode = LOG.stat().st_ino
    offset = LOG.stat().st_size
    sys.path.insert(0, SDK)
    from UE4CtrlAPI import UE4CtrlAPI
    UE4CtrlAPI().sendUE4Cmd("obj list class=BP_Balloon_C")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if simulator_pid() != pid or LOG.stat().st_ino != inode:
            raise RuntimeError("simulator process or log rotated during snapshot")
        with LOG.open("rb") as handle:
            handle.seek(offset)
            raw = handle.read()
        log = raw.decode("utf-8", "replace")
        if "Obj List: class=BP_Balloon_C" not in log:
            continue
        log = log[log.rfind("Obj List: class=BP_Balloon_C"):]
        # Unreal omits the per-class count table when the class has no live
        # objects; the final "0 Objects" line is its authoritative answer.
        counts = COUNT.findall(log)
        ids = sorted(set(ACTOR.findall(log)))
        if counts:
            reported = int(counts[-1])
        elif ZERO.search(log):
            reported = 0
        else:
            continue
        if len(ids) != reported:
            continue
        lines = [line.rstrip("\r") for line in log.splitlines()
                 if "Obj List: class=BP_Balloon_C" in line
                 or "BP_Balloon_C /" in line
                 or COUNT.search(line) or ZERO.search(line)]
        return {"wall_time": dt.datetime.now(dt.timezone.utc).isoformat(),
                "source": "ue_console_obj_list", "sim_pid": pid,
                "log_path": str(LOG), "log_inode": inode,
                "log_byte_range": [offset, offset + len(raw)],
                "actor_ids": ids, "reported_count": reported,
                "raw_lines": lines}
    raise RuntimeError("simulator did not answer actor-list command")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["before", "after", "settled"])
    parser.add_argument("trial_dir", type=Path)
    args = parser.parse_args()
    if not args.trial_dir.is_dir():
        parser.error("trial directory does not exist")
    row = snapshot()
    row["phase"] = args.phase
    output = args.trial_dir / "scene_snapshots.jsonl"
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({k: v for k, v in row.items() if k != "raw_lines"}))


if __name__ == "__main__":
    main()
