#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture the raw downward-camera frames and the ArUco debug image to disk.

Observer-only: subscribes, never publishes. Run this alongside a mission to
get ground truth about what the ArUco detector actually receives -- whether
frames arrive at all, and how large/readable the marker is in them.
"""
import os
import sys
import time

import rospy
from sensor_msgs.msg import Image


def imgmsg_to_numpy(msg):
    import numpy as np
    enc = msg.encoding.lower()
    dtype = np.uint8
    ch = 3 if enc in ("rgb8", "bgr8") else (4 if enc in ("rgba8", "bgra8") else 1)
    a = np.frombuffer(msg.data, dtype=dtype)
    if ch == 1:
        return a.reshape(msg.height, msg.width)
    a = a.reshape(msg.height, msg.width, ch)
    if enc == "rgb8":
        a = a[:, :, ::-1]
    return a


class Cap:
    def __init__(self, outdir, topic, prefix, every=1.0):
        self.outdir = outdir
        self.prefix = prefix
        self.every = every
        self.count = 0
        self.saved = 0
        self.t0 = time.time()
        self.last = 0.0
        os.makedirs(outdir, exist_ok=True)
        rospy.Subscriber(topic, Image, self.cb, queue_size=1)
        rospy.loginfo("[cap] subscribing %s -> %s/%s_*.png", topic, outdir, prefix)

    def cb(self, msg):
        self.count += 1
        now = time.time()
        if now - self.last < self.every:
            return
        self.last = now
        try:
            import cv2
            arr = imgmsg_to_numpy(msg)
            path = os.path.join(self.outdir, f"{self.prefix}_{self.saved:03d}.png")
            cv2.imwrite(path, arr)
            self.saved += 1
            rospy.loginfo("[cap] %s n=%d %dx%d enc=%s -> %s", self.prefix,
                          self.count, msg.width, msg.height, msg.encoding, path)
        except Exception as e:
            rospy.logerr("[cap] save failed: %s", e)


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/aruco_capture"
    topic = sys.argv[2] if len(sys.argv) > 2 else "/rflysim/sensor2/img_rgb"
    prefix = sys.argv[3] if len(sys.argv) > 3 else "sensor2"
    every = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    rospy.init_node("aruco_capture", anonymous=True)
    cap = Cap(outdir, topic, prefix, every)
    rospy.on_shutdown(lambda: rospy.loginfo(
        "[cap] done: %s received %d frames, saved %d", prefix, cap.count, cap.saved))
    rospy.spin()
