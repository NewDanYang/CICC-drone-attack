#include "nodes/action/wait_for_stable_position.h"

#include <cmath>

WaitForStablePosition::WaitForStablePosition(const std::string& name,
                                             const NodeConfig& config)
    : DroneActionNode(name, config) {}

PortsList WaitForStablePosition::providedPorts() {
    return {
        InputPort<Position3D>("goal", "目标位置 (x, y, z)"),
        InputPort<double>("position_threshold", 0.15, "位置误差阈值 (m)"),
        InputPort<double>("velocity_threshold", 0.08, "速度阈值 (m/s)"),
        InputPort<double>("stable_confirm_time", 0.50, "连续稳定确认时间 (s)"),
        InputPort<double>("timeout", 2.00, "最大等待时间 (s)")};
}

NodeStatus WaitForStablePosition::onStart() {
    auto goal_res = getInput<Position3D>("goal");
    if (!goal_res) {
        throw RuntimeError("Missing goal");
    }
    target_ = goal_res.value();

    position_threshold_ = getInput<double>("position_threshold").value();
    velocity_threshold_ = getInput<double>("velocity_threshold").value();
    stable_confirm_time_ = getInput<double>("stable_confirm_time").value();
    timeout_ = getInput<double>("timeout").value();

    if (position_threshold_ < 0.0 || velocity_threshold_ < 0.0 ||
        stable_confirm_time_ < 0.0 || timeout_ < 0.0) {
        throw RuntimeError("WaitForStablePosition parameters must be non-negative");
    }

    start_time_ = ros::Time::now();
    stable_since_ = ros::Time(0);
    confirmation_active_ = false;
    completed_ = false;

    ROS_INFO("[%s]: Waiting for stable position at (%.2f, %.2f, %.2f) "
             "pos<=%.2fm vel<=%.2fm/s confirm=%.2fs timeout=%.2fs",
             name().c_str(), target_.x, target_.y, target_.z,
             position_threshold_, velocity_threshold_, stable_confirm_time_,
             timeout_);
    return NodeStatus::RUNNING;
}

NodeStatus WaitForStablePosition::onRunning() {
    if (completed_) {
        return NodeStatus::SUCCESS;
    }

    const ros::Time now = ros::Time::now();
    const double elapsed = (now - start_time_).toSec();

    const auto& position = fcu_odom_ptr->pose.pose.position;
    const auto& velocity = fcu_odom_ptr->twist.twist.linear;
    const double dx = position.x - target_.x;
    const double dy = position.y - target_.y;
    const double dz = position.z - target_.z;
    const double position_error = std::sqrt(dx * dx + dy * dy + dz * dz);
    const double speed = std::sqrt(velocity.x * velocity.x +
                                   velocity.y * velocity.y +
                                   velocity.z * velocity.z);
    const bool stable = position_error <= position_threshold_ &&
                        speed <= velocity_threshold_;

    if (stable) {
        if (!confirmation_active_) {
            confirmation_active_ = true;
            stable_since_ = now;
            ROS_INFO("[%s]: stable condition met; confirmation started",
                     name().c_str());
        }

        const double confirmed_for = (now - stable_since_).toSec();
        if (confirmed_for >= stable_confirm_time_) {
            completed_ = true;
            ROS_INFO("[%s]: stable position confirmed after %.3fs", name().c_str(),
                     elapsed);
            return NodeStatus::SUCCESS;
        }
    } else if (confirmation_active_) {
        confirmation_active_ = false;
        stable_since_ = ros::Time(0);
        ROS_WARN("[%s]: stable confirmation reset", name().c_str());
    }

    // Preserve the old Delay's success behavior at its conservative upper
    // bound. This gate never turns a transient instability into a mission
    // failure and never waits longer than the configured former delay.
    if (elapsed >= timeout_) {
        completed_ = true;
        ROS_WARN("[%s]: stable wait timeout after %.3fs; proceeding",
                 name().c_str(), elapsed);
        return NodeStatus::SUCCESS;
    }

    return NodeStatus::RUNNING;
}

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<WaitForStablePosition>("WaitForStablePosition");
}
