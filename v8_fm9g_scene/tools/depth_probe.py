#!/usr/bin/env python3
"""Measure what /rflysim/sensor0/Depth_Cloud really contains.  Read-only.

The 2026-11-02 preflight sampled ONE message with width=0 while the topic ran at
20 Hz (cameras 10 Hz) with some inter-message gaps of ~1 ms -- consistent with
either "always empty" or "empty and full messages interleaved".  This decides
whether v8 uses camera depth or its size-depth fallback for the frame.

    source /opt/ros/noetic/setup.bash; source /home/ubuntu/catkin_ws/devel/setup.bash
    python3 depth_probe.py --seconds 15 --out probe_ground.json      # drone on the ground
    python3 depth_probe.py --seconds 15 --out probe_hover.json       # during a baseline flight,
                                                                     # while hovering at observe_pos
"""
import argparse
import json
import time
from collections import Counter

import numpy as np
import rospy
from sensor_msgs.msg import PointCloud2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=15.0)
    ap.add_argument('--topic', default='/rflysim/sensor0/Depth_Cloud')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    rospy.init_node('fm9g_depth_probe', anonymous=True)
    msgs = []

    def cb(m):
        n = m.width * m.height
        rec = {'t': time.monotonic(), 'stamp': m.header.stamp.to_sec(), 'frame_id': m.header.frame_id,
               'n': n, 'point_step': m.point_step, 'fields': [(f.name, f.offset, f.datatype) for f in m.fields]}
        if n:
            offs = {f.name: f.offset for f in m.fields}
            raw = np.frombuffer(m.data, dtype=np.uint8)[:n * m.point_step].reshape(n, m.point_step)
            xyz = np.stack([raw[:, offs[k]:offs[k] + 4].copy().view('<f4')[:, 0] for k in 'xyz'], 1)
            ok = np.isfinite(xyz).all(1)
            xyz = xyz[ok]
            rec['finite'] = int(ok.sum())
            if len(xyz):
                rec['min'] = xyz.min(0).round(3).tolist()
                rec['max'] = xyz.max(0).round(3).tolist()
                rec['median'] = np.median(xyz, 0).round(3).tolist()
                r = np.linalg.norm(xyz, axis=1)
                rec['range_p5_p50_p95'] = np.percentile(r, [5, 50, 95]).round(3).tolist()
        msgs.append(rec)

    rospy.Subscriber(a.topic, PointCloud2, cb, queue_size=50, buff_size=64 << 20)
    end = time.monotonic() + a.seconds
    while time.monotonic() < end and not rospy.is_shutdown():
        time.sleep(0.1)
    sizes = [m['n'] for m in msgs]
    seq = ''.join('E' if n == 0 else 'F' for n in sizes)
    full = [m for m in msgs if m['n']]
    summary = {
        'messages': len(msgs), 'rate_hz': round(len(msgs) / a.seconds, 2),
        'empty': sizes.count(0), 'full': len(full),
        'pattern_first_60': seq[:60],
        'frame_ids': dict(Counter(m['frame_id'] for m in msgs)),
        'points_per_full_msg_p50': int(np.median([m['n'] for m in full])) if full else 0,
        'fields': msgs[0]['fields'] if msgs else None,
        'sample_full': full[len(full) // 2] if full else None,
    }
    with open(a.out, 'w') as f:
        json.dump({'summary': summary, 'messages': msgs}, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
