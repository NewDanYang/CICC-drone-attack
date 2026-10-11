from pathlib import Path
import sys, shutil, hashlib, difflib

root, backup = map(Path, sys.argv[1:3])
paths = [Path('src/mission_pkg/include/nodes/action/planning_control.h'),
         Path('src/mission_pkg/src/nodes/action/planning_control.cpp'),
         Path('src/mission_pkg/src/bt_ros.cpp')]
originals = {p: (root / p).read_bytes() for p in paths}
texts = {p: b.decode('utf-8').replace('\r\n','\n') for p,b in originals.items()}
def once(text, old, new, label):
    if text.count(old)!=1:
        raise RuntimeError('Source mismatch; no changes made: '+label)
    return text.replace(old,new,1)
if any('return_view_v1' in s for s in texts.values()):
    raise RuntimeError('Return view patch already present; no changes made')
if not all('planned_navigation_v1' in s for s in texts.values()):
    raise RuntimeError('Previous navigation patch missing; no changes made')

h = once(texts[paths[0]], '#include <mutex>', '#include <mutex>\n#include <sensor_msgs/PointCloud2.h>', 'header include')
h = once(h,'    void holdPosition();','''    void holdPosition();

    // return_view_v1: turn in place and collect new cloud samples before goal.
    ros::Subscriber view_cloud_sub_;
    ros::WallTime cloud_received_wall_;
    ros::Time cloud_stamp_;
    unsigned long cloud_count_ = 0;
    unsigned long aligned_cloud_count_ = 0;
    bool face_goal_ = false;
    bool view_ready_ = false;
    double view_yaw_ = 0.0;
    ros::WallTime turn_last_wall_;
    ros::WallTime aligned_since_wall_;
    void viewCloudCallback(const sensor_msgs::PointCloud2::ConstPtr& msg);
    bool prepareForwardView();''','header view state')

c = texts[paths[1]]
c = once(c,'    planner_cmd_sub = nh->subscribe(cmd_topic, 1, &PlanningControl::plannerCmdCallback, this);',
         '''    planner_cmd_sub = nh->subscribe(cmd_topic, 1, &PlanningControl::plannerCmdCallback, this);
    view_cloud_sub_ = nh->subscribe("/cloud_registered", 1, &PlanningControl::viewCloudCallback, this);''','cloud subscription')
c = once(c,'    return { InputPort<Position3D>("goal",',
         '    return { InputPort<bool>("face_goal", false, "Turn toward goal and refresh forward cloud before planning"),\n             InputPort<Position3D>("goal",','port')
c = once(c,'void PlanningControl::holdPosition() {','''void PlanningControl::viewCloudCallback(const sensor_msgs::PointCloud2::ConstPtr& msg) {
    if (msg->width == 0 || msg->height == 0 || msg->header.stamp.isZero() ||
        msg->header.frame_id != "world") return;
    std::lock_guard<std::mutex> lock(planner_mutex_);
    cloud_received_wall_ = ros::WallTime::now();
    cloud_stamp_ = msg->header.stamp;
    ++cloud_count_;
}

bool PlanningControl::prepareForwardView() {
    if (!face_goal_ || view_ready_) return true;
    const ros::WallTime now = ros::WallTime::now();
    const double current_yaw = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
    const double error = std::atan2(std::sin(view_yaw_ - current_yaw),
                                   std::cos(view_yaw_ - current_yaw));
    const double dt = std::min(0.1, std::max(0.0, (now - turn_last_wall_).toSec()));
    turn_last_wall_ = now;
    const double setpoint_error = std::atan2(std::sin(view_yaw_ - hold_yaw_),
                                            std::cos(view_yaw_ - hold_yaw_));
    const double step = 0.5 * dt;
    hold_yaw_ += std::max(-step, std::min(step, setpoint_error));
    hold_yaw_ = std::atan2(std::sin(hold_yaw_), std::cos(hold_yaw_));
    publishPosition(hold_position_, hold_yaw_);
    if (std::abs(error) > 0.15 || std::abs(setpoint_error) > 0.15) {
        aligned_since_wall_ = ros::WallTime(0);
        ROS_INFO_THROTTLE(1.0, "[ReturnView] Turning in place: yaw_error=%.3f target_yaw=%.3f", error, view_yaw_);
        return false;
    }
    unsigned long cloud_count;
    double wall_age, stamp_age;
    {
        std::lock_guard<std::mutex> lock(planner_mutex_);
        cloud_count = cloud_count_;
        wall_age = (now - cloud_received_wall_).toSec();
        stamp_age = (ros::Time::now() - cloud_stamp_).toSec();
    }
    if (aligned_since_wall_.isZero()) {
        aligned_since_wall_ = now;
        aligned_cloud_count_ = cloud_count;
    }
    const double held = (now - aligned_since_wall_).toSec();
    const bool fresh = wall_age >= 0.0 && wall_age <= 0.5 &&
                       stamp_age >= -0.05 && stamp_age <= 0.5;
    const unsigned long samples = cloud_count - aligned_cloud_count_;
    ROS_INFO_THROTTLE(1.0, "[ReturnView] Forward view refresh: held=%.2f/1.0 cloud_samples=%lu fresh=%d", held, samples, fresh);
    if (held < 1.0 || samples < 3 || !fresh) return false;
    hold_yaw_ = view_yaw_;
    initial_yaw_ = view_yaw_;
    view_ready_ = true;
    ROS_INFO("[ReturnView] Facing goal, fresh cloud collected; ready to publish goal. yaw=%.3f samples=%lu", view_yaw_, samples);
    return true;
}

void PlanningControl::holdPosition() {''','view methods')
c = once(c,'#include <cmath>','#include <cmath>\n#include <algorithm>','algorithm include')
c = once(c,'    pending_goal_ = ps;','''    pending_goal_ = ps;
    if (face_goal_) {
        const double dx = target_x - hold_position_.x;
        const double dy = target_y - hold_position_.y;
        view_yaw_ = std::hypot(dx, dy) > tolerance ? std::atan2(dy, dx) : hold_yaw_;
    }''','bearing')
c = once(c,'    holdPosition();\n    auto off_res =', '''    holdPosition();
    face_goal_ = getInput<bool>("face_goal").value();
    view_ready_ = false;
    turn_last_wall_ = ros::WallTime::now();
    aligned_since_wall_ = ros::WallTime(0);
    auto off_res =''','start view reset')
c = once(c,'    if (!goal_sent_) {\n        if ((ros::WallTime::now()',
         '    if (!goal_sent_) {\n        if (!prepareForwardView()) return NodeStatus::RUNNING;\n        if ((ros::WallTime::now()','pre-goal view')

bt=texts[paths[2]]
begin=bt.index('    if (cmd == "land") {')
end=bt.index('\n    }',begin)+len('\n    }')
block=bt[begin:end]
if 'settle_time' not in block:
    raise RuntimeError('Landing settle missing; no changes made')
old=r'std::to_string(getDbl("land/arrival_tolerance", 0.10)) + "\" control_yaw=\"false\"/>\n"'
new=r'std::to_string(getDbl("land/arrival_tolerance", 0.10)) + "\" control_yaw=\"false\" face_goal=\"true\"/>\n"'
block=once(block,old,new,'land forward view')
bt=bt[:begin]+block+bt[end:]
bt='// return_view_v1: face landing return goal before planning.\n'+bt
patches=dict(zip(paths,(h,c,bt)))
backup.mkdir(parents=True,exist_ok=False)
diff=[]
for p in paths:
    dst=backup/p
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(root/p,dst)
    diff.extend(difflib.unified_diff(texts[p].splitlines(True),patches[p].splitlines(True),fromfile=str(p),tofile=str(p)+'.patched'))
(backup/'changes.diff').write_text(''.join(diff),encoding='utf-8')
(backup/'before_sha256.txt').write_text(''.join(hashlib.sha256(originals[p]).hexdigest()+'  '+str(p)+'\n' for p in paths),encoding='ascii')
for p in paths:
    text=patches[p]
    if b'\r\n' in originals[p] and originals[p].count(b'\r\n')==originals[p].count(b'\n'):
        text=text.replace('\n','\r\n')
    (root/p).write_bytes(text.encode('utf-8'))
    print('Patched:',p)
(backup/'restore.sh').write_text('#!/usr/bin/env bash\nset -e\n'+''.join('cp -p "'+str(backup/p)+'" "'+str(root/p)+'"\n' for p in paths)+'cd "'+str(root)+'"\ncatkin_make --pkg mission_pkg -j2\n',encoding='utf-8')
print('Backup:',backup)
print('Rollback while disarmed: stop mission node, bash',backup/'restore.sh','then restart it')

