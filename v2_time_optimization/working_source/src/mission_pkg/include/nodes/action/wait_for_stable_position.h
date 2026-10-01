#ifndef WAIT_FOR_STABLE_POSITION_H
#define WAIT_FOR_STABLE_POSITION_H

#include "base/drone_action_node.h"

/**
 * @brief Wait until the vehicle is close to a target and its speed is stable.
 *
 * This node is a passive gate. It does not publish a new flight command. The
 * preceding GoTo command remains the active command while the gate observes
 * odometry. If the conservative timeout is reached, the node succeeds so the
 * mission keeps the same failure semantics as the former fixed Delay.
 */
class WaitForStablePosition : public DroneActionNode {
public:
    WaitForStablePosition(const std::string& name, const BT::NodeConfig& config);

    static BT::PortsList providedPorts();

    BT::NodeStatus onStart() override;
    BT::NodeStatus onRunning() override;

private:
    BT::Position3D target_;
    double position_threshold_{0.15};
    double velocity_threshold_{0.08};
    double stable_confirm_time_{0.50};
    double timeout_{2.00};
    ros::Time start_time_;
    ros::Time stable_since_;
    bool confirmation_active_{false};
    bool completed_{false};
};

#endif  // WAIT_FOR_STABLE_POSITION_H
