#include "nodes/perception/multimodal_target_tracker.h"

#include <algorithm>
#include <std_msgs/String.h>

MultimodalTargetTracker::MultimodalTargetTracker(const std::string& name,
                                                 const NodeConfig& config)
    : DroneActionNode(name, config) {
    auto nh = mct->getROSHandle();
    objects_sub_ = nh->subscribe("/multimodal/objects", 1,
                                 &MultimodalTargetTracker::objectsCallback, this);
    gate_pub_ = nh->advertise<std_msgs::String>("/multimodal/balloon_target", 2, true);
}

PortsList MultimodalTargetTracker::providedPorts() {
    return {
        InputPort<std::string>("object_name", "九格确认的目标类别"),
        InputPort<double>("confidence_threshold", 0.3, "九格框有效阈值"),
        InputPort<int>("filter_window_size", 3, "仅对九格框做的平滑窗口"),
        OutputPort<PixelTarget>("pixel_target", "九格确认框的像素目标")
    };
}

void MultimodalTargetTracker::objectsCallback(const common_msgs::Objects::ConstPtr& msg) {
    std::lock_guard<std::mutex> lock(mutex_);
    last_objects_ = *msg;
    has_new_objects_ = true;
}

NodeStatus MultimodalTargetTracker::onStart() {
    target_class_ = getInput<std::string>("object_name").value();
    confidence_threshold_ = getInput<double>("confidence_threshold").value();
    filter_window_size_ = std::max(1, getInput<int>("filter_window_size").value());
    history_.clear();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        has_new_objects_ = false;
    }

    // mission_once.py uses this event to disable the YOLO publisher and start
    // the single, already-loaded FM9G4B-V image worker.
    auto color = target_class_;
    const std::string suffix = "_balloon";
    if (color.size() > suffix.size() &&
        color.compare(color.size() - suffix.size(), suffix.size(), suffix) == 0) {
        color.erase(color.size() - suffix.size());
    }
    std_msgs::String gate;
    gate.data = "start:" + color;
    gate_message_ = gate.data;
    gate_until_ = ros::Time::now() + ros::Duration(5.0);
    last_gate_publish_ = ros::Time(0);
    gate_pub_.publish(gate);
    ROS_INFO("[MultimodalTargetTracker] target=%s topic=/multimodal/objects gate=%s",
             target_class_.c_str(), gate.data.c_str());
    return NodeStatus::RUNNING;
}

void MultimodalTargetTracker::publishInvalid() {
    PixelTarget invalid;
    invalid.timestamp = ros::Time::now().toSec();
    invalid.is_detected = false;
    setOutput("pixel_target", invalid);
}

NodeStatus MultimodalTargetTracker::onRunning() {
    // The mission_once process can still be finishing model startup when this
    // BT node is constructed. Repeat the latched activation briefly so the
    // gate cannot be lost during that ROS connection window.
    const auto now = ros::Time::now();
    if (!gate_message_.empty() && now < gate_until_ &&
        (last_gate_publish_.isZero() || (now - last_gate_publish_).toSec() >= 0.2)) {
        std_msgs::String gate;
        gate.data = gate_message_;
        gate_pub_.publish(gate);
        last_gate_publish_ = now;
    }
    common_msgs::Objects objects;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!has_new_objects_) {
            publishInvalid();
            return NodeStatus::RUNNING;
        }
        objects = last_objects_;
        has_new_objects_ = false;
    }

    for (const auto& obj : objects.objects) {
        if (obj.class_name != target_class_ || obj.score < confidence_threshold_) continue;
        const double width = static_cast<double>(obj.right_bottom_x) - obj.left_top_x;
        const double height = static_cast<double>(obj.right_bottom_y) - obj.left_top_y;
        if (width <= 0.0 || height <= 0.0) continue;
        history_.emplace_back(obj.center_x, obj.center_y, width, height,
                              ros::Time::now().toSec(), true);
        while (static_cast<int>(history_.size()) > filter_window_size_) history_.pop_front();
        double cx = 0.0, cy = 0.0, w = 0.0, h = 0.0;
        for (const auto& sample : history_) {
            cx += sample.center_x; cy += sample.center_y;
            w += sample.width; h += sample.height;
        }
        const double n = static_cast<double>(history_.size());
        PixelTarget smoothed(cx / n, cy / n, w / n,
                             h / n, ros::Time::now().toSec(), true);
        setOutput("pixel_target", smoothed);
        ROS_INFO_THROTTLE(1.0, "[MultimodalTargetTracker] model bbox -> pixel_target (%.1f, %.1f) %.1fx%.1f",
                          smoothed.center_x, smoothed.center_y, smoothed.width, smoothed.height);
        return NodeStatus::RUNNING;
    }
    history_.clear();
    publishInvalid();
    return NodeStatus::RUNNING;
}

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<MultimodalTargetTracker>("MultimodalTargetTracker");
}
