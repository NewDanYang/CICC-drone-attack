#ifndef FM9G_MULTIMODAL_TARGET_TRACKER_H
#define FM9G_MULTIMODAL_TARGET_TRACKER_H
#include "base/drone_action_node.h"
#include <common_msgs/Objects.h>
#include <deque>
#include <mutex>

class MultimodalTargetTracker : public DroneActionNode {
public:
    MultimodalTargetTracker(const std::string&, const NodeConfig&);
    static PortsList providedPorts();
    NodeStatus onStart() override;
    NodeStatus onRunning() override;
    void onHalted() override;
private:
    void objectsCallback(const common_msgs::Objects::ConstPtr&);
    void publishGate(bool start);
    void invalid();
    ros::Subscriber subscriber_;
    ros::Publisher gate_;
    std::mutex mutex_;
    common_msgs::Objects objects_;
    std::deque<PixelTarget> history_;
    std::string target_, color_, session_;
    double threshold_{0.3};
    int window_{3};
    uint32_t last_sequence_{0};
    bool active_{false};
};

#endif
