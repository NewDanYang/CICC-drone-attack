from pathlib import Path
from datetime import datetime
import hashlib
import shutil
import sys
import re

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/ubuntu/catkin_ws')
backup = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/home/ubuntu/landing_settle_backup_' + datetime.now().strftime('%Y%m%dT%H%M%S'))

def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError('Source mismatch, no files changed: ' + label)
    return text.replace(old, new, 1)

patches = {}
header_path = Path('src/mission_pkg/include/nodes/action/goto.h')
source_path = Path('src/mission_pkg/src/nodes/action/goto.cpp')
bt_path = Path('src/mission_pkg/src/bt_ros.cpp')
originals = {p: (root / p).read_bytes() for p in (header_path, source_path, bt_path)}
texts = {p: b.decode('utf-8').replace('\r\n', '\n') for p, b in originals.items()}
if any('landing_settle' in t for t in texts.values()):
    raise RuntimeError('Landing settle patch already present. No changes made.')

patches[header_path] = replace_once(texts[header_path], '    bool check_yaw;', '''    bool check_yaw;

    // Optional landing_settle gate; ordinary GoTo keeps its existing behavior.
    double settle_time_ = 0.0;
    double settle_speed_threshold_ = 0.15;
    ros::Time settle_since_;
    ros::Time settle_sample_stamp_;
    geometry_msgs::Point settle_sample_position_;
    double settle_measured_speed_ = 0.0;
    bool settle_speed_valid_ = false;''', 'goto.h')

source = texts[source_path]
source = replace_once(source, '#include "utils/pose_utils.h"', '#include "utils/pose_utils.h"\n#include <cmath>', 'goto includes')
port_pattern = r'(InputPort<double>\("yaw_rate",\s*0\.5,\s*"[^"\n]*"\))\s*};'
port_matches = list(re.finditer(port_pattern, source))
if len(port_matches) != 1:
    raise RuntimeError('Source mismatch, no files changed: goto ports')
port_match = port_matches[0]
source = source[:port_match.start()] + port_match.group(1) + ''',
             InputPort<double>("settle_time", 0.0, "Time stationary before success (s)"),
             InputPort<double>("settle_speed_threshold", 0.15, "Position-derived speed limit (m/s)") };''' + source[port_match.end():]
source = replace_once(source, '    current_yaw_sp = current_yaw;', '''    // landing_settle state is reset for every execution.
    settle_time_ = getInput<double>("settle_time").value();
    settle_speed_threshold_ = getInput<double>("settle_speed_threshold").value();
    if (!std::isfinite(settle_time_) || settle_time_ < 0.0 ||
        !std::isfinite(settle_speed_threshold_) || settle_speed_threshold_ <= 0.0) {
        throw RuntimeError("Invalid GoTo settling parameters");
    }
    settle_since_ = ros::Time(0);
    settle_sample_stamp_ = ros::Time(0);
    settle_speed_valid_ = false;
    settle_measured_speed_ = 0.0;

    current_yaw_sp = current_yaw;''', 'goto start')

old = '''    if (checkArrival(target_pos, tolerance, arrival_yaw, yaw_tolerance)) {
        ROS_INFO("[%s]: GoTo completed (pos & yaw).", name().c_str());
        sendHoverCommand();
        return NodeStatus::SUCCESS;
    }

    return NodeStatus::RUNNING;'''
new = '''    bool arrived = checkArrival(target_pos, tolerance, arrival_yaw, yaw_tolerance);
    if (settle_time_ > 0.0) {
        // Simulation odometry twist may be zero while position is moving.
        // Estimate speed from distinct, fresh position samples instead.
        const ros::Time stamp = fcu_odom_ptr->header.stamp;
        const geometry_msgs::Point pos = fcu_odom_ptr->pose.pose.position;
        const double age = (now - stamp).toSec();
        const bool fresh = !stamp.isZero() && age >= 0.0 && age <= 0.5;
        if (!fresh || (!settle_sample_stamp_.isZero() && stamp < settle_sample_stamp_)) {
            settle_since_ = ros::Time(0);
            settle_sample_stamp_ = ros::Time(0);
            settle_speed_valid_ = false;
        } else if (settle_sample_stamp_.isZero()) {
            settle_sample_stamp_ = stamp;
            settle_sample_position_ = pos;
            settle_speed_valid_ = false;
        } else if (stamp > settle_sample_stamp_) {
            const double sample_dt = (stamp - settle_sample_stamp_).toSec();
            if (sample_dt >= 0.05) {
                const double dx = pos.x - settle_sample_position_.x;
                const double dy = pos.y - settle_sample_position_.y;
                const double dz = pos.z - settle_sample_position_.z;
                settle_measured_speed_ = std::sqrt(dx*dx + dy*dy + dz*dz) / sample_dt;
                settle_speed_valid_ = sample_dt <= 0.5 && std::isfinite(settle_measured_speed_);
                settle_sample_stamp_ = stamp;
                settle_sample_position_ = pos;
            }
        }
        const bool stable = fresh && arrived && settle_speed_valid_ &&
                            settle_measured_speed_ <= settle_speed_threshold_;
        if (!stable) {
            settle_since_ = ros::Time(0);
        } else if (settle_since_.isZero()) {
            settle_since_ = now;
        }
        const double held = settle_since_.isZero() ? 0.0 : (now - settle_since_).toSec();
        ROS_INFO_THROTTLE(1.0,
            "[LandingSettle] arrived=%d fresh=%d speed_valid=%d speed=%.3f limit=%.3f held=%.2f/%.2f",
            arrived, fresh, settle_speed_valid_, settle_measured_speed_,
            settle_speed_threshold_, held, settle_time_);
        if (!stable || held < settle_time_) return NodeStatus::RUNNING;
        ROS_INFO("[LandingSettle] Position settled before landing: speed=%.3f held=%.2f",
                 settle_measured_speed_, held);
    }
    if (arrived) {
        ROS_INFO("[%s]: GoTo completed (pos & yaw).", name().c_str());
        sendHoverCommand();
        return NodeStatus::SUCCESS;
    }

    return NodeStatus::RUNNING;'''
source = replace_once(source, old, new, 'goto arrival')
patches[source_path] = source

bt = texts[bt_path]
start = bt.index('    // ---- land ----')
end = bt.index('    ROS_WARN("Unknown LLM command:', start)
block = bt[start:end]
old_xml = r'"      <GoTo goal=\"" + ret_pos + "\" yaw=\"" + std::to_string(ret_yaw) + "\"/>\n"'
new_xml = r'''"      <GoTo goal=\"" + ret_pos + "\" yaw=\"" + std::to_string(ret_yaw) +
            "\" tolerance=\"" + std::to_string(getDbl("land/arrival_tolerance", 0.10)) +
            "\" settle_time=\"" + std::to_string(getDbl("land/settle_time", 1.0)) +
            "\" settle_speed_threshold=\"" + std::to_string(getDbl("land/settle_speed_threshold", 0.15)) + "\"/>\n"'''
block = replace_once(block, old_xml, new_xml, 'land return XML')
patches[bt_path] = bt[:start] + block + bt[end:]

# All matches above must pass before any deployment mutation.
backup.mkdir(parents=True, exist_ok=False)
manifest = []
for path, data in originals.items():
    target = backup / path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / path, target)
    manifest.append(hashlib.md5(data).hexdigest() + '  ' + str(path))
(backup / 'before_md5.txt').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
for path, text in patches.items():
    # Preserve each original file's CRLF/LF convention and its existing edits.
    if b'\r\n' in originals[path] and originals[path].count(b'\r\n') == originals[path].count(b'\n'):
        text = text.replace('\n', '\r\n')
    (root / path).write_bytes(text.encode('utf-8'))
    print('Patched:', path)
(backup / 'restore.sh').write_text(
    '#!/usr/bin/env bash\nset -e\n' + ''.join(
        'cp -p "' + str(backup / p) + '" "' + str(root / p) + '"\n'
        for p in originals) +
    'cd "' + str(root) + '"\ncatkin_make --pkg mission_pkg -j2\n', encoding='utf-8')
print('Backup:', backup)
print('Rollback: bash "' + str(backup / 'restore.sh') + '"; then restart mission node')

