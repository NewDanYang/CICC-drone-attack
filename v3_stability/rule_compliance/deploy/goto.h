/******************************************************************************
 * @file       goto.h
 * @brief      GoTo 行为树节点声明
 *
 * @author     郭定<1604289397@qq.com>
 * @date       2026-01-06
 ******************************************************************************/
#ifndef GOTO_H
#define GOTO_H

#include "base/drone_action_node.h"
#include <chrono>

class GoTo : public DroneActionNode {
public:
    GoTo(const std::string& name, const NodeConfig& config);

    static PortsList providedPorts();

    virtual NodeStatus onStart() override;
    virtual NodeStatus onRunning() override;

private:
    geometry_msgs::Point target_pos;
    geometry_msgs::Point current_pos_sp;
    double position_speed_limit;
    double target_yaw;
    double tolerance;
    double yaw_tolerance;

    double yaw_rate_limit;
    double current_yaw_sp;
    std::chrono::steady_clock::time_point last_loop_time;
    bool check_yaw;

    struct Handoff {
        geometry_msgs::Point position;
        double yaw;
        std::chrono::steady_clock::time_point completed;
    };
};

#endif // GOTO_H
