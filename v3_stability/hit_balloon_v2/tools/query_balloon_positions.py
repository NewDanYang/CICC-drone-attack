#!/usr/bin/env python3
"""Ask RflySim for current balloon actor transforms without moving objects."""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene_snapshot import SDK, snapshot

sys.path.insert(0, SDK)
from UE4CtrlAPI import UE4CtrlAPI


def main():
    before = snapshot()
    api = UE4CtrlAPI()
    api.initUE4MsgRec()
    time.sleep(0.3)
    results = {}
    for actor_id in before["actor_ids"]:
        for _ in range(3):
            api.reqObj([actor_id])
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                obj = api.getCamCoptObj(type_id=2, objName=actor_id)
                if obj != 0:
                    results[actor_id] = {
                        "name": obj.ObjName,
                        "pos_ue": list(obj.PosUE),
                        "box_origin_ue": list(obj.boxOrigin),
                        "box_extent_ue": list(obj.BoxExtent),
                        "timestamp": obj.timestmp,
                    }
                    break
                time.sleep(0.1)
            if actor_id in results:
                break
    after = snapshot()
    print(json.dumps({
        "sim_pid_before": before["sim_pid"],
        "sim_pid_after": after["sim_pid"],
        "actor_ids_before": before["actor_ids"],
        "actor_ids_after": after["actor_ids"],
        "objects": results,
    }, ensure_ascii=False), flush=True)
    # The SDK's receive thread is non-daemon and blocks in recvfrom. Wake it
    # explicitly so this read-only probe terminates cleanly.
    api.stopFlagUE4 = True
    api.udp_socket.sendto(b"\0", ("127.0.0.1", 20006))
    api.t4.join(timeout=2)
    api.udp_socketUE4.close()
    if before["sim_pid"] != after["sim_pid"] or before["actor_ids"] != after["actor_ids"]:
        raise RuntimeError("scene changed during transform query")


if __name__ == "__main__":
    main()
