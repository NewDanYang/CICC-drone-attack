/******************************************************************************
 * @file       target_tracker.cpp
 * @brief      TargetTracker 节点实现
 * @author     郭定<1604289397@qq.com>
 * @date       2026-01-13
 *****************************************************************************/
#include "nodes/perception/target_tracker.h"
#include <algorithm>
#include <cmath>

TargetTracker::TargetTracker(const std::string& name, const NodeConfig& config)
    : TargetDetectorBase(name, config) {
    auto nh = mct->getROSHandle();
    std::string topic;
    nh->param<std::string>("detect_result_topic", topic, "/objects");
    tracker_sub_ = nh->subscribe(topic, 1, &TargetTracker::objectsCallback, this);
}

PortsList TargetTracker::providedPorts() {
    auto ports = baseProvidedPorts();
    ports.insert(InputPort<int>("filter_window_size", 10, "像素坐标平滑窗口大小"));
    ports.insert(OutputPort<PixelTarget>("pixel_target", "像素目标（中心+尺寸）"));
    return ports;
}

NodeStatus TargetTracker::onStart() {
    NodeStatus status = TargetDetectorBase::onStart();
    filter_window_size = std::max(1, getInput<int>("filter_window_size").value());
    tracker_has_new_objects_ = false;
    pixel_history.clear();
    last_output_ = PixelTarget();
    setOutput("pixel_target", last_output_);
    return status;
}

void TargetTracker::objectsCallback(const common_msgs::Objects::ConstPtr& msg) {
    tracker_objects_ = *msg;
    received_at_ = ros::WallTime::now();
    tracker_has_new_objects_ = true;
}

bool TargetTracker::frameIsFresh() const {
    const double receipt_age = (ros::WallTime::now() - received_at_).toSec();
    const double source_age = ros::Time::now().toSec() - frame_timestamp_;
    return std::isfinite(receipt_age) && receipt_age >= 0.0 && receipt_age <= 0.3 &&
           std::isfinite(source_age) && source_age >= 0.0 && source_age <= 0.3;
}

NodeStatus TargetTracker::onRunning() {
    if (!tracker_has_new_objects_) {
        if (last_output_.is_detected && !frameIsFresh()) {
            return handleNoDetection();
        }
        return NodeStatus::RUNNING;
    }
    tracker_has_new_objects_ = false;
    // Unstamped publishers retain receipt-time semantics, while stamped frames
    // must remain fresh relative to their actual source time.
    frame_timestamp_ = tracker_objects_.header.stamp.isZero()
        ? ros::Time::now().toSec() : tracker_objects_.header.stamp.toSec();
    if (!frameIsFresh()) return handleNoDetection();
    for (const auto& obj : tracker_objects_.objects) {
        if (obj.class_name == target_class && std::isfinite(obj.score) &&
            obj.score >= confidence_threshold) {
            return handleDetectedObject(obj);
        }
    }
    return handleNoDetection();
}

NodeStatus TargetTracker::handleDetectedObject(const common_msgs::Obj& obj) {
    const double left = obj.left_top_x, top = obj.left_top_y;
    const double right = obj.right_bottom_x, bottom = obj.right_bottom_y;
    const double cx = obj.center_x, cy = obj.center_y;
    if (!std::isfinite(left) || !std::isfinite(top) || !std::isfinite(right) ||
        !std::isfinite(bottom) || !std::isfinite(cx) || !std::isfinite(cy) ||
        right <= left || bottom <= top) {
        return handleNoDetection();
    }
    pixel_history.emplace_back(cx, cy, right - left, bottom - top, frame_timestamp_, true);
    while (static_cast<int>(pixel_history.size()) > filter_window_size) {
        pixel_history.pop_front();
    }
    last_output_ = getSmoothedPixel();
    last_output_.timestamp = frame_timestamp_;
    last_output_.is_detected = true;
    setOutput("pixel_target", last_output_);
    return NodeStatus::RUNNING;
}

NodeStatus TargetTracker::handleNoDetection() {
    last_output_.is_detected = false;
    setOutput("pixel_target", last_output_);
    pixel_history.clear();
    return NodeStatus::RUNNING;
}

PixelTarget TargetTracker::getSmoothedPixel() {
    double sum_x = 0, sum_y = 0, sum_w = 0, sum_h = 0;
    for (const auto& px : pixel_history) {
        sum_x += px.center_x;
        sum_y += px.center_y;
        sum_w += px.width;
        sum_h += px.height;
    }
    const auto n = pixel_history.size();
    return PixelTarget(sum_x / n, sum_y / n, sum_w / n, sum_h / n, frame_timestamp_, true);
}

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<TargetTracker>("TargetTracker");
}
