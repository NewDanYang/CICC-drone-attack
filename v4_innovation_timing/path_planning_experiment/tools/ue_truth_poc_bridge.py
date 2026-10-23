#!/usr/bin/env python3
"""Internal concept test only: UE balloon truth -> non-target PoseArray.

This is privileged simulator data and is not a competition perception source.
The required command-line flag prevents accidental use in a normal launch.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import time

import rospy
from geometry_msgs.msg import Pose, PoseArray
from nav_msgs.msg import Odometry
from std_msgs.msg import String

from scene_snapshot import SDK, snapshot

sys.path.insert(0, SDK)
from UE4CtrlAPI import UE4CtrlAPI


def color_from_ue_position(position):
    x, y, _ = position
    if abs(y - 2.1) < 0.45:
        return "red"
    if abs(y + 2.1) < 0.45:
        return "purple"
    if abs(x - 5.6) < 0.45:
        return "blue"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--duration", type=float, default=330.0)
    parser.add_argument("--allow-ue-truth-poc", action="store_true", required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene = snapshot()
    if scene["reported_count"] != 3:
        raise RuntimeError(f"expected 3 balloon actors, got {scene['reported_count']}")

    rospy.init_node("ue_truth_poc_bridge", anonymous=True, disable_signals=True)
    state = {"target": None, "odom": None}

    def on_command(msg):
        matches = re.findall(r"(?m)^\s*hit_balloon\s*:\s*(red|purple|blue)\s*$", msg.data)
        if len(matches) == 1:
            state["target"] = matches[0]

    rospy.Subscriber("/mission_command", String, on_command, queue_size=1)
    rospy.Subscriber("/rflysim/uav1/local/odom", Odometry,
                     lambda msg: state.__setitem__("odom", msg), queue_size=1)
    pub = rospy.Publisher("/planning/poc_non_target_balloons", PoseArray, queue_size=1)
    api = UE4CtrlAPI()
    api.initUE4MsgRec()
    time.sleep(0.3)
    cache = {}
    start = time.monotonic()
    formal_lock = Path("/tmp/tcei_formal_trial.lock")
    saw_formal_lock = False
    with args.output.open("w", encoding="utf-8", buffering=1) as stream:
        stream.write(json.dumps({"event": "scene", "scene": scene}) + "\n")
        while not rospy.is_shutdown() and time.monotonic() - start < args.duration:
            for actor_id in scene["actor_ids"]:
                if formal_lock.exists():
                    saw_formal_lock = True
                elif saw_formal_lock:
                    break
                api.reqObj([actor_id])
                time.sleep(0.75)
                obj = api.getCamCoptObj(type_id=2, objName=actor_id)
                if obj != 0:
                    center_ue = [p + origin for p, origin in zip(obj.PosUE, obj.boxOrigin)]
                    color = color_from_ue_position(center_ue)
                    if color and (actor_id not in cache or
                                  obj.timestmp != cache[actor_id]["ue_timestamp"]):
                        cache[actor_id] = {
                            "color": color, "world": [center_ue[0], center_ue[1], -center_ue[2]],
                            "ue_timestamp": obj.timestmp, "received_mono": time.monotonic(),
                        }
                now = time.monotonic()
                msg = PoseArray()
                msg.header.stamp = rospy.Time.now()
                msg.header.frame_id = "world"
                published = []
                for cached_id, item in cache.items():
                    age = now - item["received_mono"]
                    if state["target"] is None or item["color"] == state["target"] or age > 2.5:
                        continue
                    pose = Pose()
                    pose.position.x, pose.position.y, pose.position.z = item["world"]
                    pose.orientation.w = 1.0
                    msg.poses.append(pose)
                    published.append({"actor_id": cached_id, "color": item["color"],
                                      "world": item["world"], "age_s": round(age, 3),
                                      "ue_timestamp": item["ue_timestamp"]})
                pub.publish(msg)
                odom = state["odom"]
                stream.write(json.dumps({
                    "event": "sample", "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "target": state["target"], "queried_actor": actor_id,
                    "query_response": obj != 0, "published": published,
                    "odom_position": [odom.pose.pose.position.x, odom.pose.pose.position.y,
                                      odom.pose.pose.position.z] if odom else None,
                }, ensure_ascii=False) + "\n")
            if saw_formal_lock and not formal_lock.exists():
                stream.write(json.dumps({"event": "formal_lock_released",
                                         "utc": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n")
                break
        stream.write(json.dumps({"event": "end", "elapsed_s": time.monotonic() - start}) + "\n")
    api.stopFlagUE4 = True
    api.udp_socket.sendto(b"\0", ("127.0.0.1", 20006))
    api.t4.join(timeout=2)
    api.udp_socketUE4.close()


if __name__ == "__main__":
    main()
