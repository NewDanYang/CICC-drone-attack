/******************************************************************************
 * @file       target_tracker.h
 * @brief      TargetTracker 节点 - 简单像素跟踪
 * @author     郭定<1604289397@qq.com>
 * @date       2026-01-13
 *****************************************************************************/
#ifndef TARGET_TRACKER_H
#define TARGET_TRACKER_H

#include "base/target_detector_base.h"
#include <deque>

class TargetTracker : public TargetDetectorBase {
public:
    TargetTracker(const std::string& name, const NodeConfig& config);
    static PortsList providedPorts();
    NodeStatus onStart() override;
    NodeStatus onRunning() override;

protected:
    NodeStatus handleDetectedObject(const common_msgs::Obj& obj) override;
    NodeStatus handleNoDetection() override;

private:
    // The base callback state is private; track receipt independently.
    ros::Subscriber tracker_sub_;
    common_msgs::Objects tracker_objects_;
    bool tracker_has_new_objects_{false};
    ros::WallTime received_at_;
    double frame_timestamp_{0.0};
    PixelTarget last_output_;
    std::deque<PixelTarget> pixel_history;
    int filter_window_size{10};
    void objectsCallback(const common_msgs::Objects::ConstPtr& msg);
    bool frameIsFresh() const;
    PixelTarget getSmoothedPixel();
};

#endif // TARGET_TRACKER_H
