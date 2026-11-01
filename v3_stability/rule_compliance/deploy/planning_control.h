#ifndef PLANNING_CONTROL_H
#define PLANNING_CONTROL_H

#include "base/drone_action_node.h"
#include <quadrotor_msgs/PositionCommand.h>
#include <mutex>

class PlanningControl : public DroneActionNode {
public:
    PlanningControl(const std::string& name, const NodeConfig& config);
    static PortsList providedPorts();
    NodeStatus onStart() override;
    NodeStatus onRunning() override;
    void onHalted() override;

private:
    void plannerCmdCallback(const quadrotor_msgs::PositionCommand::ConstPtr& msg);
    void initializeTarget(const Position3D& pos);
    void holdPosition();
    NodeStatus fail(const char* reason);

    Position3D target_pos_;
    double tolerance = 0.2;
    double offset_z = 0.0;
    bool control_yaw = false;
    double initial_yaw_ = 0.0;
    bool target_initialized = false;
    ros::Publisher planner_goal_pub;
    ros::Subscriber planner_cmd_sub;
    quadrotor_msgs::PositionCommand last_planner_cmd;
    std::mutex mutex_;
    bool active_ = false;
    bool goal_sent_ = false;
    bool has_planner_cmd = false;
    bool have_previous_id_ = false;
    unsigned int previous_id_ = 0;
    ros::Time goal_stamp_;
    ros::WallTime start_wall_;
    ros::WallTime sent_wall_;
    ros::WallTime received_wall_;
    geometry_msgs::PoseStamped pending_goal_;
    geometry_msgs::Point hold_position_;
    double hold_yaw_ = 0.0;
};
#endif
