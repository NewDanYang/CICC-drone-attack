#!/usr/bin/env python3
"""Observe real ROS mapping and balloon actors during one baseline trial.

The UE actor query is ground truth for measurement only. This node publishes
nothing and never feeds UE coordinates to the planner or flight controller.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import time

import numpy as np
import rospy
from common_msgs.msg import Objects
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2
from sensor_msgs import point_cloud2

from scene_snapshot import SDK, snapshot

sys.path.insert(0, SDK)
from UE4CtrlAPI import UE4CtrlAPI


def iso_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def stamp(msg):
    return msg.header.stamp.to_sec() if msg is not None else None


def cloud_summary(msg, centers):
    if msg is None:
        return None
    points = np.asarray(list(point_cloud2.read_points(
        msg, field_names=("x", "y", "z"), skip_nans=True)), dtype=np.float32)
    result = {"stamp": stamp(msg), "frame": msg.header.frame_id,
              "points": len(points), "near_actors": {}}
    if not len(points):
        return result
    for actor_id, ue_center in centers.items():
        if ue_center is None:
            continue
        result["near_actors"][actor_id] = {}
        # UE and ROS have opposite vertical conventions in this scene. Keep
        # both readings visible until the live cloud establishes the mapping.
        for name, center in ("ue", ue_center), ("z_flip", ue_center * [1, 1, -1]):
            distances = np.linalg.norm(points - center, axis=1)
            nearby = points[distances < 0.6]
            result["near_actors"][actor_id][name] = {
                "min_distance_m": round(float(distances.min()), 4),
                "within_0p3m": int((distances < 0.3).sum()),
                "within_0p6m": int(len(nearby)),
                "points_within_0p6m_first_100": nearby[:100].round(3).tolist(),
            }
    return result


def projection_summary(cloud, detections, odom):
    """Project the existing world cloud into sensor1's FOV 90 RGB image."""
    if cloud is None or detections is None or odom is None:
        return None
    q = odom.pose.pose.orientation
    x, y, z, w = q.x, q.y, q.z, q.w
    rotation = np.asarray([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])
    p = odom.pose.pose.position
    camera = np.asarray([p.x, p.y, p.z]) + rotation @ [0.2, 0.0, 0.0]
    world = np.asarray(list(point_cloud2.read_points(
        cloud, field_names=("x", "y", "z"), skip_nans=True)), dtype=np.float32)
    out = {"cloud_stamp": stamp(cloud), "objects_stamp": stamp(detections),
           "odom_stamp": stamp(odom), "camera_world": camera.tolist(),
           "intrinsics": {"fx": 320.0, "fy": 320.0, "cx": 320.0, "cy": 240.0},
           "balloons": []}
    if len(world) == 0:
        return out
    body = (world - camera) @ rotation
    forward = body[:, 0]
    valid = forward > 0.2
    u = 320.0 - 320.0 * body[:, 1] / np.maximum(forward, 0.2)
    v = 240.0 - 320.0 * body[:, 2] / np.maximum(forward, 0.2)
    for det in detections.objects:
        if "balloon" not in det.class_name:
            continue
        inside = (valid & (u >= det.left_top_x) & (u <= det.right_bottom_x)
                  & (v >= det.left_top_y) & (v <= det.right_bottom_y))
        cloud_roi = world[inside]
        depths = forward[inside]
        row = {"class_name": det.class_name,
               "bbox": [det.left_top_x, det.left_top_y,
                        det.right_bottom_x, det.right_bottom_y],
               "point_count": int(len(cloud_roi))}
        if len(cloud_roi):
            q20 = np.quantile(depths, 0.2)
            near = cloud_roi[depths <= q20]
            row.update({"depth_quantiles_m": np.quantile(depths, [0.0, 0.2, 0.5, 0.8, 1.0]).round(3).tolist(),
                        "near_20pct_world_median": np.median(near, axis=0).round(3).tolist(),
                        "roi_points_first_100": cloud_roi[:100].round(3).tolist()})
        out["balloons"].append(row)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--duration", type=float, default=330.0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene = snapshot()
    if scene["reported_count"] != 3:
        raise RuntimeError(f"expected 3 balloons, got {scene['reported_count']}")
    rospy.init_node("planning_feasibility_probe", anonymous=True, disable_signals=True)
    latest = {"objects": None, "cloud": None, "occupancy": None,
              "occupancy_inflate": None, "odom": None}
    for key, topic, kind in [
        ("objects", "/objects", Objects),
        ("cloud", "/cloud_registered", PointCloud2),
        ("occupancy", "/grid_map/occupancy", PointCloud2),
        ("occupancy_inflate", "/grid_map/occupancy_inflate", PointCloud2),
        ("odom", "/rflysim/uav1/local/odom", Odometry),
    ]:
        rospy.Subscriber(topic, kind, lambda msg, name=key: latest.__setitem__(name, msg),
                         queue_size=1)
    api = UE4CtrlAPI()
    api.initUE4MsgRec()
    time.sleep(0.5)
    with args.output.open("w", encoding="utf-8", buffering=1) as stream:
        stream.write(json.dumps({"event": "scene_before", "scene": scene}) + "\n")
        start = time.monotonic()
        iteration = 0
        while not rospy.is_shutdown() and time.monotonic() - start < args.duration:
            iteration += 1
            centers = {}
            actors = {}
            for actor_id in scene["actor_ids"]:
                api.reqObj([actor_id])
                time.sleep(0.75)
                obj = api.getCamCoptObj(type_id=2, objName=actor_id)
                if obj == 0:
                    centers[actor_id] = None
                    actors[actor_id] = None
                else:
                    center = np.asarray(obj.PosUE) + np.asarray(obj.boxOrigin)
                    centers[actor_id] = center
                    actors[actor_id] = {
                        "pos_ue": list(obj.PosUE), "box_origin": list(obj.boxOrigin),
                        "box_extent": list(obj.BoxExtent), "center": center.tolist(),
                        "ue_timestamp": obj.timestmp,
                    }
            detections = latest["objects"]
            odom = latest["odom"]
            row = {"event": "sample", "utc": iso_now(), "iteration": iteration,
                   "actors": actors,
                   "objects_stamp": stamp(detections),
                   "objects": [{"class_name": x.class_name, "score": x.score,
                                "bbox": [x.left_top_x, x.left_top_y,
                                         x.right_bottom_x, x.right_bottom_y]}
                               for x in detections.objects] if detections else None,
                   "odom_stamp": stamp(odom),
                   "odom_position": [odom.pose.pose.position.x, odom.pose.pose.position.y,
                                     odom.pose.pose.position.z] if odom else None,
                   "cloud": cloud_summary(latest["cloud"], centers),
                   "occupancy": cloud_summary(latest["occupancy"], centers),
                   "occupancy_inflate": cloud_summary(latest["occupancy_inflate"], centers),
                   "cloud_projection": projection_summary(latest["cloud"], detections, odom)}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            time.sleep(max(0.0, args.interval - 2.25))
        stream.write(json.dumps({"event": "end", "utc": iso_now(),
                                 "elapsed_s": time.monotonic() - start}) + "\n")
    api.stopFlagUE4 = True
    api.udp_socket.sendto(b"\0", ("127.0.0.1", 20006))
    api.t4.join(timeout=2)
    api.udp_socketUE4.close()


if __name__ == "__main__":
    main()
