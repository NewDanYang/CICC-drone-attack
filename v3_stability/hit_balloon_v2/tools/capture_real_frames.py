#!/usr/bin/env python3
"""Save low-rate raw simulator camera frames and odometry for visual diagnosis.

The input is the actual ROS sensor topic, never generated or synthetic data.
Run this before a formal trial and stop it after the trial. Images are JPEG;
frame metadata stays in frames.jsonl in the same directory.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
import threading
import time

import cv2
import numpy as np
import rospy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image


def yaw_from_quaternion(q):
    return float(np.arctan2(2 * (q.w * q.z + q.x * q.y),
                            1 - 2 * (q.y * q.y + q.z * q.z)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--image-topic", default="/rflysim/sensor1/img_rgb",
                        help="image topic used by /object_detection_node")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rospy.init_node("hit_balloon_frame_capture", anonymous=True)
    state = {"last": 0.0, "count": 0, "odom": None}
    lock = threading.Lock()
    stream = (args.output_dir / "frames.jsonl").open("a", encoding="utf-8", buffering=1)

    def on_odom(msg):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        with lock:
            state["odom"] = {"x": p.x, "y": p.y, "z": p.z,
                             "yaw": yaw_from_quaternion(q)}

    def on_image(msg):
        now = time.time()
        with lock:
            if now - state["last"] < args.interval:
                return
            state["last"] = now
            state["count"] += 1
            count = state["count"]
            pose = state["odom"]
        if msg.encoding not in ("rgb8", "bgr8") or msg.step < msg.width * 3:
            rospy.logwarn_throttle(5, "unsupported image encoding or stride: %s", msg.encoding)
            return
        pixels = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)
        pixels = pixels[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
        if msg.encoding == "rgb8":
            pixels = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
        stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        name = f"{stamp}_{count:04d}.jpg"
        if not cv2.imwrite(str(args.output_dir / name), pixels,
                           [int(cv2.IMWRITE_JPEG_QUALITY), 90]):
            rospy.logerr("could not save camera frame %s", name)
            return
        stream.write(json.dumps({"wall_time": dt.datetime.fromtimestamp(
            now, dt.timezone.utc).isoformat(), "image": name,
            "image_topic": args.image_topic, "encoding": msg.encoding,
            "width": msg.width, "height": msg.height,
            "odom": pose}) + "\n")

    rospy.Subscriber("/mavros/local_position/odom", Odometry, on_odom, queue_size=1)
    rospy.Subscriber(args.image_topic, Image, on_image, queue_size=1,
                     buff_size=4 * 1024 * 1024)
    rospy.spin()
    stream.close()


if __name__ == "__main__":
    main()
