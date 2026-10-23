#!/usr/bin/env python3
"""Read-only UE actor transform time series and scene object listing.

Run only with a settled, disarmed simulator and no formal trial lock.
The JSONL records every request, including missing and cached responses.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene_snapshot import LOG, SDK, snapshot

sys.path.insert(0, SDK)
from UE4CtrlAPI import UE4CtrlAPI


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def object_data(obj):
    return {
        "name": obj.ObjName,
        "pos_ue": list(obj.PosUE),
        "box_origin_ue": list(obj.boxOrigin),
        "box_extent_ue": list(obj.BoxExtent),
        "angle_euler": list(obj.angEuler),
        "ue_timestamp": obj.timestmp,
    }


def log_section(api, command, pause=2.0):
    offset = LOG.stat().st_size
    api.sendUE4Cmd(command)
    time.sleep(pause)
    with LOG.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read()
    return {"command": command, "log_byte_range": [offset, offset + len(raw)],
            "raw": raw.decode("utf-8", "replace")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--interval", type=float, default=0.75)
    args = parser.parse_args()
    if args.samples < 10 or not 0.5 <= args.interval <= 1.0:
        parser.error("require at least 10 samples at 0.5-1.0 s intervals")
    if Path("/tmp/tcei_formal_trial.lock").exists():
        parser.error("formal trial lock exists")
    args.output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    if before["reported_count"] != 3:
        parser.error(f"expected three balloon actors, got {before['reported_count']}")
    api = UE4CtrlAPI()
    api.initUE4MsgRec()
    time.sleep(0.3)
    try:
        sections = []
        for command in ["obj list class=StaticMeshActor", "obj list class=BP_Wall1_C",
                        "obj list class=BP_Wall2_C", "obj list class=BP_Floor_C",
                        "obj list class=BP_FloorEX_C", "obj list"]:
            sections.append(log_section(api, command, 2.0))
        (args.output / "object_lists.json").write_text(
            json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8")
        wall_names = sorted(set(re.findall(
            r"(?:BP_Wall[12]_C|BP_Floor(?:EX)?_C) /\S*?PersistentLevel\."
            r"([A-Za-z0-9_]+)", "\n".join(s["raw"] for s in sections))))
        with (args.output / "actors.jsonl").open("w", encoding="utf-8") as stream:
            for actor_id in before["actor_ids"] + wall_names:
                target = args.samples if actor_id in before["actor_ids"] else 3
                max_count = target * 14 if actor_id in before["actor_ids"] else 20
                unique_timestamps = set()
                api.reqObj([actor_id])
                for sample in range(max_count):
                    time.sleep(args.interval)
                    api.reqObj([actor_id])
                    obj = api.getCamCoptObj(type_id=2, objName=actor_id)
                    row = {"utc": utc_now(), "sample": sample, "actor_id": actor_id,
                           "response": object_data(obj) if obj != 0 else None}
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    if obj != 0:
                        unique_timestamps.add(obj.timestmp)
                    if len(unique_timestamps) >= target:
                        break
                print(json.dumps({"actor": actor_id, "unique_responses":
                                  len(unique_timestamps), "attempts": sample + 1}), flush=True)
        after = snapshot()
        (args.output / "manifest.json").write_text(json.dumps({
            "utc": utc_now(), "before": before, "after": after,
            "samples": args.samples, "interval_s": args.interval,
            "scene_unchanged": before["sim_pid"] == after["sim_pid"]
            and before["actor_ids"] == after["actor_ids"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(args.output), "sim_pid": before["sim_pid"],
                          "actors": before["actor_ids"], "wall_names": wall_names,
                          "samples": args.samples,
                          "scene_unchanged": before["sim_pid"] == after["sim_pid"]
                          and before["actor_ids"] == after["actor_ids"]}), flush=True)
    finally:
        api.stopFlagUE4 = True
        api.udp_socket.sendto(b"\0", ("127.0.0.1", 20006))
        api.t4.join(timeout=2)
        api.udp_socketUE4.close()


if __name__ == "__main__":
    main()
