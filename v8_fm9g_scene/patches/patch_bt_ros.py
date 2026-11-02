"""Byte-checked patch of mission_pkg/src/bt_ros.cpp for the FM9G scene stages.

Adds, in front of each official template, an alternative template used when
the ROS param /fm9g_scene/enabled is true (default true once this binary is
deployed).  `rosparam set /fm9g_scene/enabled false` restores the exact
official XML for the next mission without rebuilding.

Usage:  python3 patch_bt_ros.py <in bt_ros.cpp> <out bt_ros.cpp>
"""
import hashlib
import sys

OFFICIAL_MD5 = 'f3883b30c69f3bdc248d50ac9fc0ad9e'   # == server copy (6.3 report)

GET_BOOL = r'''    auto getBool = [&](const std::string& key, bool def) -> bool {
        bool val;
        if (!nh.getParam(key, val)) val = def;
        return val;
    };
    const bool fm9g = getBool("fm9g_scene/enabled", true);
    const std::string fm9g_n = std::to_string((int)getDbl("fm9g_scene/min_samples", 3));
    const std::string fm9g_spread = std::to_string(getDbl("fm9g_scene/max_spread", 0.3));
    auto withZ = [](const std::string& pos, double z) -> std::string {
        // "x;y;z" -> "x;y;<z>"
        size_t cut = pos.rfind(';');
        return (cut == std::string::npos ? pos : pos.substr(0, cut)) + ";" + std::to_string(z);
    };
'''

CROSS = r'''        if (fm9g) {
            std::string t = std::to_string(getDbl("fm9g_scene/frame_timeout", 45.0));
            return
                "      <GoTo goal=\"" + observe + "\"/>\n"
                "      <Delay delay_msec=\"" + delay + "\">\n"
                "        <AlwaysSuccess/>\n"
                "      </Delay>\n"
                "      <!-- FM9G4B-V 识别方框 + 深度相机测距 -->\n"
                "      <Fm9gLocate object_name=\"square_frame\" expected_pos=\"" + exp_pos + "\" "
                "xy_tolerance=\"1.0\" z_tolerance=\"" + z_tol + "\" "
                "min_samples=\"" + fm9g_n + "\" max_spread=\"" + fm9g_spread + "\" timeout=\"" + t + "\" "
                "position=\"{frame_center}\"/>\n"
                "      <PlanningControl goal=\"{frame_center}\" offset_z=\"" + offset_z + "\" final_position=\"{planning_end_pos}\"/>\n";
        }
'''

ARUCO = r'''        if (fm9g) {
            std::string t = std::to_string(getDbl("fm9g_scene/aruco_timeout", 20.0));
            return
                "      <GoTo goal=\"" + hover + "\"/>\n"
                "      <!-- FM9G4B-V 下视定位二维码, 对准后由 OpenCV 解码 -->\n"
                "      <Fm9gLocate object_name=\"aruco_marker\" ground_target=\"true\" "
                "fallback_pos=\"" + hover + "\" min_samples=\"" + fm9g_n + "\" max_spread=\"" + fm9g_spread + "\" "
                "timeout=\"" + t + "\" position=\"{aruco_hover}\"/>\n"
                "      <GoTo goal=\"{aruco_hover}\"/>\n"
                "      <Parallel success_count=\"2\" failure_count=\"1\">\n"
                "        <GoTo goal=\"{aruco_hover}\"/>\n"
                "        <ArucoDetector aruco_id=\"{detected_aruco_id}\"/>\n"
                "      </Parallel>\n";
        }
'''

RETURN = r'''        std::string fm9g_return_obs = getStr("fm9g_scene/return_observe_pos", "4.6;-0.4;1.0");
        if (fm9g && !fm9g_return_obs.empty()) {
            std::string t = std::to_string(getDbl("fm9g_scene/return_timeout", 25.0));
            return
                "      <GoTo goal=\"" + turn_pos + "\" yaw=\"" + std::to_string(turn_yaw) + "\"/>\n"
                "      <!-- FM9G4B-V 反向重新识别方框 (失败时沿用正向感知结果) -->\n"
                "      <GoTo goal=\"" + fm9g_return_obs + "\" yaw=\"" + std::to_string(turn_yaw) + "\"/>\n"
                "      <Fm9gLocate object_name=\"square_frame\" expected_pos=\"{frame_center}\" "
                "xy_tolerance=\"0.6\" z_tolerance=\"0.5\" min_samples=\"" + fm9g_n + "\" max_spread=\"" + fm9g_spread + "\" "
                "timeout=\"" + t + "\" fallback_pos=\"{frame_center}\" position=\"{frame_center_return}\"/>\n"
                "      <GoTo goal=\"{planning_end_pos}\"/>\n"
                "      <PlanningControl goal=\"{frame_center_return}\"/>\n"
                "      <GoTo goal=\"" + body_fwd + "\" frame=\"1\"/>\n"
                "      <GoTo goal=\"" + body_fwd + "\" frame=\"1\" yaw=\"" + std::to_string(exit_yaw) + "\"/>\n";
        }
'''

LAND = r'''        if (fm9g) {
            std::string t = std::to_string(getDbl("fm9g_scene/land_timeout", 20.0));
            std::string obs = withZ(ret_pos, getDbl("fm9g_scene/land_observe_z", 1.2));
            return
                "      <GoTo goal=\"" + obs + "\" yaw=\"" + std::to_string(ret_yaw) + "\"/>\n"
                "      <!-- FM9G4B-V 下视定位起降标识 -->\n"
                "      <Fm9gLocate object_name=\"landing_pad\" ground_target=\"true\" "
                "fallback_pos=\"" + ret_pos + "\" min_samples=\"" + fm9g_n + "\" max_spread=\"" + fm9g_spread + "\" "
                "timeout=\"" + t + "\" position=\"{landing_pos}\"/>\n"
                "      <GoTo goal=\"{landing_pos}\" yaw=\"" + std::to_string(ret_yaw) + "\"/>\n"
                "      <Land/>\n";
        }
'''

# (anchor that must occur exactly once, text inserted immediately BEFORE it)
EDITS = [
    ('    // ---- takeoff ----\n', GET_BOOL + '\n'),
    ('        return \n            "      <!-- 移动到观察位置 -->\\n"', CROSS),
    ('        return\n            "      <GoTo goal=\\"" + hover + "\\"/>\\n"', ARUCO),
    ('        return\n            "      <!-- 旋转180度 -->\\n"', RETURN),
    ('        return\n            "      <!-- 返回起点 -->\\n"', LAND),
]


def patch(source: bytes) -> bytes:
    digest = hashlib.md5(source).hexdigest()
    if digest != OFFICIAL_MD5:
        raise SystemExit('bt_ros.cpp MD5 %s != official %s; refusing (re-derive anchors first)'
                         % (digest, OFFICIAL_MD5))
    crlf = b'\r\n' in source
    text = source.decode('utf-8').replace('\r\n', '\n')
    if 'Fm9gLocate' in text:
        raise SystemExit('already patched')
    for anchor, insert in EDITS:
        if text.count(anchor) != 1:
            raise SystemExit('anchor count %d for %r' % (text.count(anchor), anchor[:60]))
        text = text.replace(anchor, insert + anchor)
    out = text.replace('\n', '\r\n') if crlf else text
    return out.encode('utf-8')


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    data = patch(open(src, 'rb').read())
    open(dst, 'xb').write(data)
    print('patched', dst, hashlib.md5(data).hexdigest())
