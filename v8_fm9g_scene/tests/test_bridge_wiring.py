"""End-to-end wiring of SceneBridge with fake ROS modules and a stubbed model.

Checks message decoding (Image, PointCloud2 xyz offsets), odom/stamp matching,
the front (depth) and down (ground-plane) paths, every rejection gate, and
what actually gets published.  The model is stubbed: this does NOT test FM9G
accuracy -- tools/offline_eval.py does that on real frames on the server.
"""
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
sys.path.insert(0, str(ROOT / 'tests'))


# ---------------------------------------------------------------- fake ROS
class _Msg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Stamp:
    def __init__(self, t=0.0):
        self.t = t

    def to_sec(self):
        return self.t


class _Header:
    def __init__(self, t=0.0):
        self.stamp = _Stamp(t)
        self.frame_id = ''
        self.seq = 0


class _Time:
    current = 100.0

    @staticmethod
    def now():
        return _Stamp(_Time.current)

    @staticmethod
    def from_sec(t):
        return _Stamp(t)


PUBLISHED = []


class _Pub:
    def __init__(self, topic, *a, **k):
        self.topic = topic

    def publish(self, msg):
        PUBLISHED.append((self.topic, msg))


def _install_fake_ros():
    rospy = types.ModuleType('rospy')
    rospy.Publisher = _Pub
    rospy.Subscriber = lambda *a, **k: None
    rospy.Time = _Time
    rospy.get_param = lambda name, default=None: default
    for f in ('loginfo', 'logwarn', 'logerr', 'logwarn_throttle', 'logerr_throttle'):
        setattr(rospy, f, lambda *a, **k: None)
    sys.modules['rospy'] = rospy
    for mod, names in {'geometry_msgs.msg': ['PointStamped'], 'nav_msgs.msg': ['Odometry'],
                       'sensor_msgs.msg': ['Image', 'PointCloud2'], 'std_msgs.msg': ['String']}.items():
        pkg = mod.split('.')[0]
        sys.modules.setdefault(pkg, types.ModuleType(pkg))
        m = types.ModuleType(mod)
        for n in names:
            setattr(m, n, type(n, (), {'__init__': lambda self: setattr(self, 'header', _Header()) or
                                       setattr(self, 'point', _Msg(x=0, y=0, z=0))}))
        sys.modules[mod] = m


_install_fake_ros()
from fm9g_scene import bridge as B          # noqa: E402
from fm9g_scene import geometry as g        # noqa: E402
from fm9g_scene.targets import TARGETS      # noqa: E402
import test_geometry as tg                  # noqa: E402


class StubModel:
    def __init__(self, native, probs):
        self.native, self.probs = native, probs

    def native_boxes(self, bgr, spec, decision):
        return self.native

    def verify(self, bgr, boxes, spec, decision):
        return self.probs[:len(boxes)]


def image_msg(stamp):
    data = np.full((480, 640, 3), 90, np.uint8)
    return _Msg(header=_Header(stamp), width=640, height=480, encoding='rgb8',
                step=640 * 3, data=data.tobytes())


def cloud_msg(points_sensor, stamp):
    pts = np.asarray(points_sensor, dtype='<f4')
    # 16-byte points: x y z + padding, like many RflySim/PCL clouds
    rec = np.zeros((len(pts), 4), '<f4')
    rec[:, :3] = pts
    fields = [_Msg(name='x', offset=0), _Msg(name='y', offset=4), _Msg(name='z', offset=8)]
    return _Msg(header=_Header(stamp), fields=fields, width=len(pts), height=1,
                point_step=16, data=rec.tobytes())


def odom_msg(pos, yaw, stamp):
    q = g.yaw_quat(yaw)
    return _Msg(header=_Header(stamp), pose=_Msg(pose=_Msg(
        position=_Msg(x=pos[0], y=pos[1], z=pos[2]),
        orientation=_Msg(x=q[0], y=q[1], z=q[2], w=q[3]))))


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('FM9G_SCENE_EVIDENCE_ROOT', str(tmp_path))
    monkeypatch.setenv('FM9G_SCENE_WINDOW', '0')
    monkeypatch.setenv('FM9G_SCENE_IDLE', '')
    monkeypatch.setattr(B, 'SceneModel', lambda *a, **k: None)
    br = B.SceneBridge(None, None, None, None, None)
    PUBLISHED.clear()
    yield br
    br.close()


def to_native(box):
    return (int(box[0] * 1000 / 640), int(box[1] * 1000 / 480),
            int(math.ceil(box[2] * 1000 / 640)), int(math.ceil(box[3] * 1000 / 480)))


def run_front(br, native, probs, stamp=100.0):
    box, R = tg.frame_box_at(tg.OBSERVE)
    br.sm = StubModel(native(box), probs)
    br.on_odom(odom_msg(tg.OBSERVE, 0.0, stamp - 0.01))
    br.on_cloud(cloud_msg(tg.synthetic_frame_cloud(tg.OBSERVE, R, step=4), stamp - 0.05))
    br.on_image(image_msg(stamp), 'front')
    br.on_request(_Msg(data='start square_frame r1'))
    br.request = (br.request[0], br.request[1], stamp - 1.0)
    br.step(TARGETS['square_frame'], br.request)
    return box


def test_true_frame_box_is_published_at_true_position(bridge):
    run_front(bridge, lambda b: [to_native(b)], [0.93])
    pubs = [m for t, m in PUBLISHED if t == '/fm9g/target_world/square_frame']
    assert len(pubs) == 1
    p = np.array([pubs[0].point.x, pubs[0].point.y, pubs[0].point.z])
    assert np.linalg.norm(p - tg.FRAME) < 0.12, p


def test_oversized_box_is_rejected_by_depth_gate(bridge):
    def big(b):
        cu, cv, s = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 1.8 * (b[2] - b[0])
        return [to_native([cu - s / 2, cv - s / 2, cu + s / 2, cv + s / 2])]
    run_front(bridge, big, [0.95])
    assert not [m for t, m in PUBLISHED if t.startswith('/fm9g/target_world')]
    assert any(t == '/fm9g/scene_debug_image' for t, _ in PUBLISHED)   # still shown


def test_low_verify_score_is_not_published(bridge):
    run_front(bridge, lambda b: [to_native(b)], [0.62])     # the 6.3 debug-image score
    assert not [m for t, m in PUBLISHED if t.startswith('/fm9g/target_world')]


def test_stale_image_before_request_is_ignored(bridge):
    box, R = tg.frame_box_at(tg.OBSERVE)
    bridge.sm = StubModel([to_native(box)], [0.9])
    bridge.on_odom(odom_msg(tg.OBSERVE, 0.0, 99.99))
    bridge.on_image(image_msg(100.0), 'front')
    bridge.request = ('square_frame', 'r1', 100.5)        # request after the image
    bridge.step(TARGETS['square_frame'], bridge.request)
    assert not PUBLISHED


@pytest.mark.parametrize('yaw', [0.0, math.pi / 2])
def test_down_camera_marker_published_on_ground(bridge, yaw):
    pos = np.array([4.5, 0.5, 1.2])
    marker = np.array([4.7, 0.3, 0.0])
    R = g.quat_to_R(*g.yaw_quat(yaw))
    half = 0.3
    corners = []
    for dx in (-half, half):
        for dy in (-half, half):
            pb = R.T @ (marker + [dx, dy, 0] - pos)
            pc = g.DOWN_CAM_R.T @ pb
            corners.append((320 + 320 * pc[0] / pc[2], 240 + 320 * pc[1] / pc[2]))
    box = [min(c[0] for c in corners), min(c[1] for c in corners),
           max(c[0] for c in corners), max(c[1] for c in corners)]
    bridge.sm = StubModel([to_native(box)], [0.88])
    bridge.on_odom(odom_msg(pos, yaw, 99.99))
    bridge.on_image(image_msg(100.0), 'down')
    bridge.request = ('aruco_marker', 'r2', 99.0)
    bridge.step(TARGETS['aruco_marker'], bridge.request)
    pubs = [m for t, m in PUBLISHED if t == '/fm9g/target_world/aruco_marker']
    assert len(pubs) == 1
    p = np.array([pubs[0].point.x, pubs[0].point.y])
    assert np.linalg.norm(p - marker[:2]) < 0.03


def test_down_camera_implausible_size_rejected(bridge):
    bridge.sm = StubModel([(0, 0, 1000, 1000)], [0.9])    # whole image = 2.4 m wide at 1.2 m
    bridge.on_odom(odom_msg([0, 0, 1.2], 0.0, 99.99))
    bridge.on_image(image_msg(100.0), 'down')
    bridge.request = ('landing_pad', 'r3', 99.0)
    bridge.step(TARGETS['landing_pad'], bridge.request)
    assert not [m for t, m in PUBLISHED if t.startswith('/fm9g/target_world')]


def test_request_protocol(bridge):
    bridge.on_request(_Msg(data='start landing_pad a'))
    first = bridge.request
    bridge.on_request(_Msg(data='start landing_pad a'))      # periodic re-send
    assert bridge.request == first
    bridge.on_request(_Msg(data='stop landing_pad a'))
    assert bridge.request is None
    bridge.on_request(_Msg(data='start balloon x'))           # not ours
    assert bridge.request is None


def test_camera_clock_in_another_domain_still_works(bridge):
    """Camera header stamps 5000 s away from ROS time (sim/wall clock mismatch):
    pose must be matched by receive time and the sample stamped in ROS time."""
    pos, yaw = np.array([4.5, 0.5, 1.2]), 0.0
    bridge.sm = StubModel([to_native([290, 210, 350, 270])], [0.9])
    bridge.on_odom(odom_msg(pos, yaw, 0.0))          # header 0: no header match possible
    bridge.on_image(image_msg(5100.0), 'down')        # foreign clock
    bridge.request = ('aruco_marker', 'r9', 99.0)     # ROS-time request start
    bridge.step(TARGETS['aruco_marker'], bridge.request)
    pubs = [m for t, m in PUBLISHED if t == '/fm9g/target_world/aruco_marker']
    assert len(pubs) == 1
    assert pubs[0].header.stamp.to_sec() == _Time.current      # ROS receive time, not 5100
    assert np.allclose([pubs[0].point.x, pubs[0].point.y], pos[:2], atol=0.01)
