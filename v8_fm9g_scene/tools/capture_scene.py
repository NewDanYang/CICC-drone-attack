#!/usr/bin/env python3
"""Record real frames for offline evaluation during an ordinary (official) trial.

Saves, at --rate Hz per camera: the image (jpg), the odom pose nearest to its
stamp, and for the front camera the depth cloud nearest in time (every
--cloud-stride-th point, float16 npz).  Read-only: publishes nothing.

Run with the ROS python (not the conda env) while a baseline trial flies:
    source /opt/ros/noetic/setup.bash; source /home/ubuntu/catkin_ws/devel/setup.bash
    python3 capture_scene.py --out /root/gpufree-data/fm9g_v8/capture_$(date +%Y%m%dT%H%M%S)
Stops on /mission_result or Ctrl-C.
"""
import argparse
import json
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import rospy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, PointCloud2
from std_msgs.msg import String


def decode_bgr(msg):
    ch = {'rgb8': 3, 'bgr8': 3, 'rgba8': 4, 'bgra8': 4}[msg.encoding]
    rows = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
    arr = rows[:, :msg.width * ch].reshape(msg.height, msg.width, ch)[:, :, :3]
    return (arr[:, :, ::-1] if msg.encoding.startswith('rgb') else arr).copy()


def decode_cloud(msg, stride):
    offs = {f.name: f.offset for f in msg.fields}
    n = msg.width * msg.height
    raw = np.frombuffer(msg.data, dtype=np.uint8)[:n * msg.point_step].reshape(n, msg.point_step)[::stride]
    xyz = np.stack([raw[:, offs[k]:offs[k] + 4].copy().view('<f4')[:, 0] for k in 'xyz'], 1)
    return xyz[np.isfinite(xyz).all(1)]


class Capture:
    def __init__(self, a):
        self.out = Path(a.out)
        for d in ('front', 'down', 'cloud'):
            (self.out / d).mkdir(parents=True, exist_ok=False)
        self.period = 1.0 / a.rate
        self.stride = a.cloud_stride
        self.lock = threading.Lock()
        self.odom = deque(maxlen=400)
        self.clouds = deque(maxlen=6)
        self.last = {'front': 0.0, 'down': 0.0}
        self.index = (self.out / 'index.jsonl').open('w', buffering=1)
        self.done = False
        rospy.Subscriber(a.odom, Odometry, self.on_odom, queue_size=50)
        rospy.Subscriber('/rflysim/sensor0/Depth_Cloud', PointCloud2, self.on_cloud,
                         queue_size=1, buff_size=16 << 20)
        rospy.Subscriber('/rflysim/sensor1/img_rgb', Image, self.on_image, 'front', queue_size=1, buff_size=4 << 20)
        rospy.Subscriber('/rflysim/sensor2/img_rgb', Image, self.on_image, 'down', queue_size=1, buff_size=4 << 20)
        rospy.Subscriber('/mission_result', String, self.on_result, queue_size=2)

    @staticmethod
    def stamp(msg):
        return msg.header.stamp.to_sec()

    @staticmethod
    def nearest(items, header, recv, header_tol, recv_tol):
        # same rule as the flight bridge: header stamps first, else ROS receive time
        if not items:
            return None, None
        if header > 0:
            b = min(items, key=lambda o: abs(o[0] - header))
            if b[0] > 0 and abs(b[0] - header) <= header_tol:
                return b, 'header'
        b = min(items, key=lambda o: abs(o[1] - recv))
        return (b, 'receive') if abs(b[1] - recv) <= recv_tol else (None, None)

    def on_odom(self, m):
        p, q = m.pose.pose.position, m.pose.pose.orientation
        with self.lock:
            self.odom.append((self.stamp(m), rospy.Time.now().to_sec(), [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]))

    def on_cloud(self, m):
        with self.lock:
            self.clouds.append((self.stamp(m), rospy.Time.now().to_sec(), m))

    def on_result(self, m):
        self.index.write(json.dumps({'kind': 'mission_result', 'data': m.data[:500]}) + '\n')
        self.done = True

    def on_image(self, msg, cam):
        header, t = self.stamp(msg), rospy.Time.now().to_sec()
        if t - self.last[cam] < self.period:
            return
        self.last[cam] = t
        with self.lock:
            odom, oclock = self.nearest(list(self.odom), header, t, 0.2, 0.1)
            cloud, cclock = (self.nearest(list(self.clouds), header, t, 0.35, 0.35)
                             if cam == 'front' else (None, None))
        if odom is None:
            return
        name = '%.3f' % t
        cv2.imwrite(str(self.out / cam / (name + '.jpg')), decode_bgr(msg), [cv2.IMWRITE_JPEG_QUALITY, 95])
        rec = {'kind': 'frame', 'camera': cam, 'stamp': t, 'header_stamp': header,
               'image': '%s/%s.jpg' % (cam, name), 'pos': odom[2], 'quat': odom[3], 'odom_clock': oclock}
        if cloud is not None:
            np.savez_compressed(self.out / 'cloud' / (name + '.npz'),
                                xyz=decode_cloud(cloud[2], self.stride).astype(np.float16))
            rec.update(cloud='cloud/%s.npz' % name, cloud_clock=cclock)
        self.index.write(json.dumps(rec) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--rate', type=float, default=2.0)
    ap.add_argument('--cloud-stride', type=int, default=8)
    ap.add_argument('--odom', default='/rflysim/uav1/local/odom')
    a = ap.parse_args()
    rospy.init_node('fm9g_scene_capture', anonymous=True)
    c = Capture(a)
    rospy.loginfo('capturing to %s', a.out)
    r = rospy.Rate(5)
    while not rospy.is_shutdown() and not c.done:
        r.sleep()
    rospy.sleep(1.0)


if __name__ == '__main__':
    main()
