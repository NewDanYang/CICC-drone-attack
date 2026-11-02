/******************************************************************************
 * @file       goto.cpp
 * @brief      GoTo 行为树节点 - 飞往指定位置
 *
 * @author     郭定<1604289397@qq.com>
 * @date       2026-01-06
 ******************************************************************************/
#include "nodes/action/goto.h"
#include "nodes/action/goto_ramp.hpp"
#include "utils/pose_utils.h"

GoTo::GoTo(const std::string& name, const NodeConfig& config)
    : DroneActionNode(name, config) {}

PortsList GoTo::providedPorts() {
    return { InputPort<Position3D>("goal", "目标位置 (x, y, z), 为空则保持当前位置"),
             InputPort<double>("yaw", "目标绝对航向 (rad), 为空则保持当前航向"),
             InputPort<int>("frame", 0, "坐标系: 0=世界系(默认), 1=机体系"),
             InputPort<double>("tolerance", "到达容差"),
             InputPort<double>("yaw_tolerance", "偏航到达容差(rad)"),
             InputPort<bool>("continue_previous", false, "仅紧邻上一 GoTo 时延续其终点设定值"),
             InputPort<double>("max_speed", 0.5, "位置设定点最大三维速度 (m/s)"),
             InputPort<double>("yaw_rate", 0.5, "最大偏航角速度 (rad/s)") };
}

NodeStatus GoTo::onStart() {
    // 获取当前位置和航向
    geometry_msgs::Point current_pos = fcu_odom_ptr->pose.pose.position;
    const auto& orientation = fcu_odom_ptr->pose.pose.orientation;
    const bool finite_orientation = std::isfinite(orientation.x) && std::isfinite(orientation.y) &&
        std::isfinite(orientation.z) && std::isfinite(orientation.w);
    double current_yaw = finite_orientation
        ? PoseUtils::getYawFromQuat(orientation)
        : std::numeric_limits<double>::quiet_NaN();

    const bool valid_odom = goto_motion::finitePoint(current_pos) && std::isfinite(current_yaw);
    auto reject_invalid = [this, valid_odom]() {
        ROS_ERROR("[%s]: GoTo rejected non-finite geometry, yaw, or tolerance.", name().c_str());
        if (valid_odom) {
            sendHoverCommand();
        }
        return NodeStatus::FAILURE;
    };
    if (!valid_odom) {
        return reject_invalid();
    }
    current_yaw = goto_motion::normalizedYaw(current_yaw);

    const auto start_time = std::chrono::steady_clock::now();
    Handoff handoff;
    const bool continue_command = getInput<bool>("continue_previous").value() &&
        config().blackboard->get("goto_motion_handoff", handoff) &&
        std::chrono::duration<double>(start_time - handoff.completed).count() <= 0.1;
    config().blackboard->set("goto_motion_handoff",
        Handoff{current_pos, current_yaw, start_time - std::chrono::seconds(1)});

    // 解析目标位置
    auto goal_res = getInput<Position3D>("goal");
    auto frame_res = getInput<int>("frame");
    int frame = frame_res.value();

    if (goal_res) {
        Position3D goal = goal_res.value();
        if (frame == 1) {  // 1 = 机体系
            // 机体坐标系转世界坐标系：
            // goal.x = 机体前进方向
            // goal.y = 机体左移方向
            // 需要根据当前yaw角度旋转到世界坐标系
            target_pos.x = current_pos.x + goal.x * std::cos(current_yaw) - goal.y * std::sin(current_yaw);
            target_pos.y = current_pos.y + goal.x * std::sin(current_yaw) + goal.y * std::cos(current_yaw);
            target_pos.z = current_pos.z + goal.z;
        } else {  // 0 = 世界系(默认)
            target_pos.x = goal.x;
            target_pos.y = goal.y;
            target_pos.z = goal.z;
        }
    } else {
        target_pos = continue_command ? handoff.position : current_pos;
    }

    // 解析航向
    auto yaw_res = getInput<double>("yaw");
    if (yaw_res) {
        target_yaw = yaw_res.value();
        check_yaw = true;
    } else {
        target_yaw = continue_command ? handoff.yaw : current_yaw;
        check_yaw = false;
    }
    if (!std::isfinite(target_yaw)) {
        return reject_invalid();
    }
    target_yaw = goto_motion::normalizedYaw(target_yaw);

    auto tol_res = getInput<double>("tolerance");
    if (tol_res) {
        tolerance = tol_res.value();
    } else {
        ros::NodeHandle nh;
        nh.param("tolerance", tolerance, 0.2);
    }

    auto yaw_tol_res = getInput<double>("yaw_tolerance");
    if (yaw_tol_res) {
        yaw_tolerance = yaw_tol_res.value();
    } else {
        ros::NodeHandle nh;
        nh.param("yaw_tolerance", yaw_tolerance, 0.15);
    }
    if (!std::isfinite(tolerance) || tolerance < 0.0 ||
        !std::isfinite(yaw_tolerance) || yaw_tolerance < 0.0) {
        return reject_invalid();
    }

    auto yaw_rate_res = getInput<double>("yaw_rate");
    yaw_rate_limit = yaw_rate_res.value();
    position_speed_limit = getInput<double>("max_speed").value();
    if (!std::isfinite(position_speed_limit) || position_speed_limit <= 0.0 ||
        !std::isfinite(yaw_rate_limit) || yaw_rate_limit <= 0.0 ||
        !goto_motion::finitePoint(target_pos) ||
        !goto_motion::finiteSegment(current_pos, target_pos)) {
        return reject_invalid();
    }

    current_pos_sp = continue_command ? handoff.position : current_pos;
    current_yaw_sp = continue_command ? handoff.yaw : current_yaw;
    if (!goto_motion::finiteSegment(current_pos_sp, target_pos) ||
        !std::isfinite(current_yaw_sp)) {
        return reject_invalid();
    }
    current_yaw_sp = goto_motion::normalizedYaw(current_yaw_sp);
    last_loop_time = std::chrono::steady_clock::now();
    publishPosition(current_pos_sp, current_yaw_sp);

    ROS_INFO("[%s]: GoTo start -> target: (%.2f, %.2f, %.2f), yaw: %.2f, frame: %d, tol: %.2f, yaw_tol: %.2f, yaw_rate: %.2f, max_speed: %.2f",
             name().c_str(), target_pos.x, target_pos.y, target_pos.z, target_yaw, frame, tolerance, yaw_tolerance, yaw_rate_limit, position_speed_limit);
    return NodeStatus::RUNNING;
}

NodeStatus GoTo::onRunning() {
    const auto now = std::chrono::steady_clock::now();
    const double dt = goto_motion::boundedDt(
        std::chrono::duration<double>(now - last_loop_time).count());
    last_loop_time = now;
    const bool position_command_arrived = goto_motion::advancePosition(
        current_pos_sp, target_pos, position_speed_limit, dt);

    // 偏航角平滑插值 (Ramp)
    double yaw_error = target_yaw - current_yaw_sp;

    // 归一化误差到 [-PI, PI]
    yaw_error = goto_motion::normalizedYaw(yaw_error);

    double max_step = yaw_rate_limit * dt;
    const bool yaw_command_arrived = std::abs(yaw_error) <= max_step;

    if (yaw_command_arrived) {
        current_yaw_sp = target_yaw;
    } else {
        current_yaw_sp += (yaw_error > 0 ? 1.0 : -1.0) * max_step;
    }

    // 归一化设定点 (防止长期累积溢出，虽然 cos/sin 无所谓，但保持规范)
    current_yaw_sp = goto_motion::normalizedYaw(current_yaw_sp);

    publishPosition(current_pos_sp, current_yaw_sp);

    double arrival_yaw = check_yaw ? target_yaw : std::numeric_limits<double>::quiet_NaN();
    if (position_command_arrived && yaw_command_arrived &&
        checkArrival(target_pos, tolerance, arrival_yaw, yaw_tolerance)) {
        ROS_INFO("[%s]: GoTo completed (pos & yaw).", name().c_str());
        config().blackboard->set("goto_motion_handoff",
            Handoff{target_pos, current_yaw_sp, std::chrono::steady_clock::now()});
        // Keep the exact endpoint; hover capture would replace it with drifting odometry.
        return NodeStatus::SUCCESS;
    }

    return NodeStatus::RUNNING;
}

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<GoTo>("GoTo");
}
