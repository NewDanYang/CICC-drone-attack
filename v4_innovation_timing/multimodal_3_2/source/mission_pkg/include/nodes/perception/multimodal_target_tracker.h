#ifndef MULTIMODAL_TARGET_TRACKER_H
#define MULTIMODAL_TARGET_TRACKER_H

#include "base/drone_action_node.h"
#include <common_msgs/Objects.h>
#include <deque>
#include <mutex>

/**
 * Consumes only /multimodal/objects, whose semantic detections are produced
 * by the FM9G4B-V bridge in mission_once.py.  It never subscribes to /objects
 * (the YOLO path).  The node smooths a model-confirmed bbox for VisualServo;
 * it does not classify or search for objects itself.
 */
class MultimodalTargetTracker : public DroneActionNode {
public:
    MultimodalTargetTracker(const std::string& name, const NodeConfig& config);
    static PortsList providedPorts();
    NodeStatus onStart() override;
    NodeStatus onRunning() override;

private:
    void objectsCallback(const common_msgs::Objects::ConstPtr& msg);
    void publishInvalid();

    ros::Subscriber objects_sub_;
    ros::Publisher gate_pub_;
    common_msgs::Objects last_objects_;
    bool has_new_objects_{false};
    std::mutex mutex_;
    std::string target_class_;
    double confidence_threshold_{0.3};
    int filter_window_size_{3};
    std::string gate_message_;
    ros::Time gate_until_;
    ros::Time last_gate_publish_;
    std::deque<PixelTarget> history_;
};

#endif
