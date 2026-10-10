from pathlib import Path
from datetime import datetime
import hashlib
import shutil
import sys
import re
import difflib

root = Path(sys.argv[1])
backup = Path(sys.argv[2])
paths = [Path('src/mission_pkg/include/nodes/action/planning_control.h'),
         Path('src/mission_pkg/src/nodes/action/planning_control.cpp'),
         Path('src/mission_pkg/src/bt_ros.cpp')]
originals = {p: (root / p).read_bytes() for p in paths}
texts = {p: b.decode('utf-8').replace('\r\n', '\n') for p, b in originals.items()}

def once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError('Source mismatch; no changes made: ' + label)
    return text.replace(old, new, 1)

if any('planned_navigation_v1' in t for t in texts.values()):
    raise RuntimeError('Patch already present; no changes made')

h = texts[paths[0]]
h = once(h, '#include <quadrotor_msgs/PositionCommand.h>',
         '#include <quadrotor_msgs/PositionCommand.h>\n#include <mutex>', 'header include')
h = once(h, '    virtual NodeStatus onRunning() override;',
         '    virtual NodeStatus onRunning() override;\n    virtual void onHalted() override;', 'halt declaration')
h = once(h, '    bool has_planner_cmd;', '''    bool has_planner_cmd;

    // planned_navigation_v1: hold while waiting for a new, fresh trajectory.
    std::mutex planner_mutex_;
    bool active_ = false;
    bool goal_sent_ = false;
    bool have_previous_id_ = false;
    unsigned int previous_id_ = 0;
    ros::Time goal_stamp_;
    ros::WallTime start_wall_;
    ros::WallTime command_received_wall_;
    double command_timeout_ = 0.5;
    geometry_msgs::PoseStamped pending_goal_;
    geometry_msgs::Point hold_position_;
    double hold_yaw_ = 0.0;
    bool holding_ = false;
    void holdPosition();''', 'header members')

c = texts[paths[1]]
required = ['planner_goal_pub.publish(ps);', '    if (!has_planner_cmd) return NodeStatus::RUNNING;',
            '    last_planner_cmd = *msg;\n    has_planner_cmd = true;']
for marker in required:
    if c.count(marker) != 1:
        raise RuntimeError('PlanningControl differs from inspected source; no changes made')
c = once(c, '#include <tf2_geometry_msgs/tf2_geometry_msgs.h>',
         '#include <tf2_geometry_msgs/tf2_geometry_msgs.h>\n#include <cmath>', 'source include')
c = once(c, '    last_planner_cmd = *msg;\n    has_planner_cmd = true;', '''    std::lock_guard<std::mutex> lock(planner_mutex_);
    last_planner_cmd = *msg;
    if (!active_) return;
    if (!goal_sent_) {
        previous_id_ = msg->trajectory_id;
        have_previous_id_ = true;
        return;
    }
    // The topic has no goal ID. A changed trajectory ID rejects a continuing
    // previous trajectory when its ID was observed before goal publication.
    if (msg->header.stamp.isZero() || msg->header.stamp < goal_stamp_ ||
        (have_previous_id_ && msg->trajectory_id == previous_id_)) return;
    const double age = (ros::Time::now() - msg->header.stamp).toSec();
    if (age < -0.05 || age > command_timeout_ ||
        !std::isfinite(msg->position.x) || !std::isfinite(msg->position.y) ||
        !std::isfinite(msg->position.z) || !std::isfinite(msg->yaw)) return;
    command_received_wall_ = ros::WallTime::now();
    has_planner_cmd = true;''', 'callback')
# Do not overwrite a previously accepted command with a rejected callback.
c = c.replace('    last_planner_cmd = *msg;\n    if (!active_) return;', '    if (!active_) return;', 1)
c = c.replace('    command_received_wall_ = ros::WallTime::now();',
              '    last_planner_cmd = *msg;\n    command_received_wall_ = ros::WallTime::now();', 1)
c = once(c, '    planner_goal_pub.publish(ps);\n    has_planner_cmd = false;',
         '    pending_goal_ = ps;\n    // Publish after a short baseline window and subscriber connection.', 'goal delay')
c = once(c, 'NodeStatus PlanningControl::onStart() {', '''void PlanningControl::holdPosition() {
    if (!holding_) {
        hold_position_ = fcu_odom_ptr->pose.pose.position;
        hold_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
        holding_ = true;
    }
    publishPosition(hold_position_, hold_yaw_);
}

void PlanningControl::onHalted() {
    {
        std::lock_guard<std::mutex> lock(planner_mutex_);
        active_ = false;
        has_planner_cmd = false;
    }
    holding_ = false;
    holdPosition();
    ROS_INFO("[PlanningGuard] Halted; holding current position.");
}

NodeStatus PlanningControl::onStart() {
    // planned_navigation_v1
    {
        std::lock_guard<std::mutex> lock(planner_mutex_);
        active_ = false;
        goal_sent_ = false;
        have_previous_id_ = false;
        has_planner_cmd = false;
        goal_stamp_ = ros::Time(0);
    }
    target_initialized = false;
    holding_ = false;
    start_wall_ = ros::WallTime::now();
    ros::NodeHandle guard_nh;
    guard_nh.param("planning_guard/command_timeout", command_timeout_, 0.5);
    if (!std::isfinite(command_timeout_) || command_timeout_ <= 0.0) {
        throw RuntimeError("Invalid planning_guard/command_timeout");
    }
    {
        std::lock_guard<std::mutex> lock(planner_mutex_);
        active_ = true;
    }
    holdPosition();''', 'start reset')
# Replace only this node's old hover helper calls.
c = c.replace('sendHoverCommand();', 'holdPosition();')
running = 'NodeStatus PlanningControl::onRunning() {\n'
c = once(c, running, running + '''    const double odom_age = (ros::Time::now() - fcu_odom_ptr->header.stamp).toSec();
    if (fcu_odom_ptr->header.stamp.isZero() || odom_age < -0.05 || odom_age > 0.5) {
        holdPosition();
        ROS_WARN_THROTTLE(1.0, "[PlanningGuard] Stale odometry; holding.");
        return NodeStatus::RUNNING;
    }
''', 'odom guard')
pos = c.index('    geometry_msgs::Point target;', c.index(running))
insert = '''    if (!goal_sent_) {
        if ((ros::WallTime::now() - start_wall_).toSec() < 0.3 ||
            planner_goal_pub.getNumSubscribers() == 0) {
            holdPosition();
            ROS_WARN_THROTTLE(1.0, "[PlanningGuard] Waiting for goal subscriber/baseline; holding.");
            return NodeStatus::RUNNING;
        }
        {
            std::lock_guard<std::mutex> lock(planner_mutex_);
            has_planner_cmd = false;
            goal_stamp_ = ros::Time::now();
            pending_goal_.header.stamp = goal_stamp_;
            goal_sent_ = true;
        }
        planner_goal_pub.publish(pending_goal_);
        ROS_INFO("[PlanningGuard] Goal sent in world: (%.2f, %.2f, %.2f)",
                 target_pos_.x, target_pos_.y, target_pos_.z);
    }

'''
c = c[:pos] + insert + c[pos:]
c = once(c, '    if (!has_planner_cmd) return NodeStatus::RUNNING;', '''    quadrotor_msgs::PositionCommand command;
    bool fresh = false;
    {
        std::lock_guard<std::mutex> lock(planner_mutex_);
        const double stamp_age = (ros::Time::now() - last_planner_cmd.header.stamp).toSec();
        const double receive_age = (ros::WallTime::now() - command_received_wall_).toSec();
        fresh = has_planner_cmd && stamp_age >= -0.05 && stamp_age <= command_timeout_ &&
                receive_age >= 0.0 && receive_age <= command_timeout_;
        if (fresh) command = last_planner_cmd;
    }
    if (!fresh) {
        holdPosition();
        ROS_WARN_THROTTLE(1.0, "[PlanningGuard] Waiting for fresh trajectory; holding (cancel mission if persistent).");
        return NodeStatus::RUNNING;
    }
    if (holding_) ROS_INFO("[PlanningGuard] Fresh trajectory accepted: id=%u", command.trajectory_id);
    holding_ = false;''', 'command freshness')
c = c.replace('geometry_msgs::Point ego_pos = last_planner_cmd.position;',
              'geometry_msgs::Point ego_pos = command.position;')
c = c.replace('control_yaw ? last_planner_cmd.yaw : initial_yaw_',
              'control_yaw ? command.yaw : initial_yaw_')

bt = texts[paths[2]]
begin = bt.index('    if (cmd == "detect_aruco") {')
end = bt.index('\n    }', begin) + len('\n    }')
block = bt[begin:end]
old = r'"      <GoTo goal=\"" + hover + "\"/>\n"'
new = r'"      <PlanningControl goal=\"" + hover + "\" tolerance=\"0.10\" control_yaw=\"false\"/>\n"'
block = once(block, old, new, 'ArUco first GoTo')
bt = bt[:begin] + block + bt[end:]
begin = bt.index('    if (cmd == "land") {')
end = bt.index('\n    }', begin) + len('\n    }')
block = bt[begin:end]
if 'settle_time' not in block or 'settle_speed_threshold' not in block:
    raise RuntimeError('Landing settle patch missing; no changes made')
old = r'"      <GoTo goal=\"" + ret_pos + "\" yaw=\"" + std::to_string(ret_yaw) +'
new = r'''"      <PlanningControl goal=\"" + ret_pos + "\" tolerance=\"" +
            std::to_string(getDbl("land/arrival_tolerance", 0.10)) + "\" control_yaw=\"false\"/>\n"
            "      <GoTo goal=\"" + ret_pos + "\" yaw=\"" + std::to_string(ret_yaw) +'''
block = once(block, old, new, 'land preceding planning stage')
bt = bt[:begin] + block + bt[end:]
bt = '// planned_navigation_v1: ArUco transit and land return use PlanningControl.\n' + bt
patched = dict(zip(paths, (h, c, bt)))

# Validate all source matches before backups and source mutations.
backup.mkdir(parents=True, exist_ok=False)
diff = []
hashes = []
for p in paths:
    dst = backup / p
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / p, dst)
    hashes.append(hashlib.sha256(originals[p]).hexdigest() + '  ' + str(p))
    diff.extend(difflib.unified_diff(texts[p].splitlines(True), patched[p].splitlines(True),
                                  fromfile=str(p), tofile=str(p) + '.patched'))
(backup / 'before_sha256.txt').write_text('\n'.join(hashes) + '\n', encoding='ascii')
(backup / 'changes.diff').write_text(''.join(diff), encoding='utf-8')
for p in paths:
    data = patched[p]
    if b'\r\n' in originals[p] and originals[p].count(b'\r\n') == originals[p].count(b'\n'):
        data = data.replace('\n', '\r\n')
    (root / p).write_bytes(data.encode('utf-8'))
    print('Patched:', p)
(backup / 'restore.sh').write_text(
    '#!/usr/bin/env bash\nset -e\n' + ''.join(
        'cp -p "' + str(backup / p) + '" "' + str(root / p) + '"\n' for p in paths) +
    'cd "' + str(root) + '"\ncatkin_make --pkg mission_pkg -j2\n', encoding='utf-8')
print('Backup:', backup)
print('Rollback while disarmed: stop mission node, bash', backup / 'restore.sh', 'then restart it')

