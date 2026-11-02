#include "nodes/action/planning_control.h"
#include "utils/pose_utils.h"
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <cmath>

PlanningControl::PlanningControl(const std::string& name, const NodeConfig& config)
    : DroneActionNode(name, config) {
    auto nh = mct->getROSHandle();
    std::string goal_topic, cmd_topic;
    nh->param<std::string>("goal_topic", goal_topic, "/move_base_simple/goal");
    nh->param<std::string>("planner_cmd_topic", cmd_topic, "/planning/pos_cmd");
    planner_goal_pub = nh->advertise<geometry_msgs::PoseStamped>(goal_topic, 10);
    planner_cmd_sub = nh->subscribe(cmd_topic, 1, &PlanningControl::plannerCmdCallback, this);
}

PortsList PlanningControl::providedPorts() {
    return {InputPort<Position3D>("goal", "目标点(x;y;z)"),
            InputPort<double>("offset_z", 0.0, "相对于目标的Z轴偏移(随飞机航向)"),
            InputPort<double>("tolerance", "到达容差"),
            InputPort<bool>("control_yaw", false, "是否控制偏航角"),
            OutputPort<Position3D>("final_position", "到达的最终位置(x;y;z)")};
}

void PlanningControl::plannerCmdCallback(const quadrotor_msgs::PositionCommand::ConstPtr& msg) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!active_) return;
    if (!goal_sent_) {
        previous_id_ = msg->trajectory_id;
        have_previous_id_ = true;
        return;
    }
    const double age = (ros::Time::now() - msg->header.stamp).toSec();
    const auto& goal = pending_goal_.pose.position;
    // traj_server refreshes the stamp even for an old trajectory's final hover.
    if (!std::isfinite(age) || msg->header.stamp.isZero() || msg->header.stamp < goal_stamp_ ||
        age < -0.05 || age > 0.5 || msg->header.frame_id != "world" ||
        msg->trajectory_flag != quadrotor_msgs::PositionCommand::TRAJECTORY_STATUS_READY ||
        (have_previous_id_ && msg->trajectory_id == previous_id_) ||
        !std::isfinite(msg->goal_pos.x) || !std::isfinite(msg->goal_pos.y) ||
        !std::isfinite(msg->goal_pos.z) ||
        std::abs(msg->goal_pos.x - goal.x) > 0.001 ||
        std::abs(msg->goal_pos.y - goal.y) > 0.001 ||
        std::abs(msg->goal_pos.z - goal.z) > 0.001 ||
        !std::isfinite(msg->position.x) || !std::isfinite(msg->position.y) ||
        !std::isfinite(msg->position.z) || !std::isfinite(msg->yaw)) return;
    last_planner_cmd = *msg;
    received_wall_ = ros::WallTime::now();
    has_planner_cmd = true;
}

void PlanningControl::initializeTarget(const Position3D& pos) {
    target_pos_ = pos;
    target_pos_.x += offset_z * std::cos(initial_yaw_);
    target_pos_.y += offset_z * std::sin(initial_yaw_);
    pending_goal_ = geometry_msgs::PoseStamped();
    pending_goal_.header.frame_id = "world";
    pending_goal_.pose.position.x = target_pos_.x;
    pending_goal_.pose.position.y = target_pos_.y;
    pending_goal_.pose.position.z = target_pos_.z;
    pending_goal_.pose.orientation.w = 1.0;
    target_initialized = true;
    ROS_INFO("[%s]: Target acquired! Planning navigation start -> (%.2f, %.2f, %.2f), offset: %.2f",
             name().c_str(), target_pos_.x, target_pos_.y, target_pos_.z, offset_z);
}

void PlanningControl::holdPosition() {
    publishPosition(hold_position_, hold_yaw_);
}

NodeStatus PlanningControl::fail(const char* reason) {
    active_ = false;
    has_planner_cmd = false;
    holdPosition();
    ROS_ERROR("[PlanningGuard] %s; holding and failing without resending goal.", reason);
    return NodeStatus::FAILURE;
}

NodeStatus PlanningControl::onStart() {
    std::lock_guard<std::mutex> lock(mutex_);
    active_ = true;
    goal_sent_ = false;
    has_planner_cmd = false;
    have_previous_id_ = false;
    target_initialized = false;
    start_wall_ = ros::WallTime::now();
    hold_position_ = fcu_odom_ptr->pose.pose.position;
    initial_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
    hold_yaw_ = initial_yaw_;
    offset_z = getInput<double>("offset_z").value();
    control_yaw = getInput<bool>("control_yaw").value();
    auto tol = getInput<double>("tolerance");
    if (tol) tolerance = tol.value();
    else {
        ros::NodeHandle nh;
        nh.param("tolerance", tolerance, 0.2);
    }
    auto goal = getInput<Position3D>("goal");
    if (goal) initializeTarget(goal.value());
    holdPosition();
    return NodeStatus::RUNNING;
}

NodeStatus PlanningControl::onRunning() {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto now = ros::WallTime::now();
    const double elapsed = (now - start_wall_).toSec();
    if (!target_initialized) {
        auto goal = getInput<Position3D>("goal");
        if (goal) initializeTarget(goal.value());
        else if (elapsed >= 3.0) return fail("Goal input timeout");
        else { holdPosition(); return NodeStatus::RUNNING; }
    }
    if (!goal_sent_) {
        if (elapsed >= 3.0) return fail("Goal subscriber handshake timeout");
        if ((elapsed < 0.3 && !have_previous_id_) || planner_goal_pub.getNumSubscribers() == 0 ||
            planner_cmd_sub.getNumPublishers() == 0) {
            holdPosition();
            return NodeStatus::RUNNING;
        }
        goal_stamp_ = ros::Time::now();
        pending_goal_.header.stamp = goal_stamp_;
        sent_wall_ = now;
        goal_sent_ = true;
        planner_goal_pub.publish(pending_goal_);
        ROS_INFO("[PlanningGuard] Goal sent once in world: (%.2f, %.2f, %.2f)",
                 target_pos_.x, target_pos_.y, target_pos_.z);
    }
    if (!has_planner_cmd) {
        if ((now - sent_wall_).toSec() >= 5.0) return fail("First trajectory response timeout");
        holdPosition();
        return NodeStatus::RUNNING;
    }
    const double stamp_age = (ros::Time::now() - last_planner_cmd.header.stamp).toSec();
    if ((now - received_wall_).toSec() > 0.5 || stamp_age > 0.5 || stamp_age < -0.05) {
        hold_position_ = fcu_odom_ptr->pose.pose.position;
        hold_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
        return fail("Trajectory stream timeout");
    }
    if (checkArrival(pending_goal_.pose.position, tolerance)) {
        Position3D final_pos;
        final_pos.x = fcu_odom_ptr->pose.pose.position.x;
        final_pos.y = fcu_odom_ptr->pose.pose.position.y;
        final_pos.z = fcu_odom_ptr->pose.pose.position.z;
        setOutput("final_position", final_pos);
        hold_position_ = fcu_odom_ptr->pose.pose.position;
        hold_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
        active_ = false;
        holdPosition();
        ROS_INFO("[%s]: Planning navigation completed.", name().c_str());
        return NodeStatus::SUCCESS;
    }
    publishPosition(last_planner_cmd.position, control_yaw ? last_planner_cmd.yaw : initial_yaw_);
    return NodeStatus::RUNNING;
}

void PlanningControl::onHalted() {
    std::lock_guard<std::mutex> lock(mutex_);
    active_ = false;
    has_planner_cmd = false;
    hold_position_ = fcu_odom_ptr->pose.pose.position;
    hold_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
    holdPosition();
}

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<PlanningControl>("PlanningControl");
}
