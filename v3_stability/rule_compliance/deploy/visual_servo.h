#ifndef VISUAL_SERVO_H
#define VISUAL_SERVO_H

#include "base/drone_action_node.h"
#include <ros/time.h>
#include <deque>

class VisualServo : public DroneActionNode {
public:
    VisualServo(const std::string& name, const NodeConfig& config);
    static PortsList providedPorts();
    NodeStatus onStart() override;
    NodeStatus onRunning() override;
private:
    enum ServoState { ALIGN, APPROACHING, SPRINTING };
    ServoState current_state_;
    PixelTarget last_target_;
    bool has_ever_received_data_;
    bool target_valid_;
    bool derivative_ready_;
    bool new_observation_;
    double last_observation_stamp_;
    double observation_dt_;
    double yaw_command_, vz_command_;
    double max_area_ratio_;
    std::string target_color_;
    bool search_anchor_active_;
    bool sprint_aborted_;
    bool close_encounter_pending_;
    ros::Time close_encounter_stamp_, close_encounter_lost_at_;
    geometry_msgs::Point search_anchor_;
    double search_base_yaw_;
    ros::Time search_start_time_, sprint_start_time_;
    int align_stable_frames_;
    double img_cx_, img_cy_;
    int img_w_, img_h_;
    double k_p_yaw_rate_, k_d_yaw_rate_, max_yaw_rate_, deadzone_yaw_;
    double img_fx_, yaw_feedforward_gain_;
    bool bearing_ready_;
    bool bearing_pending_;
    double pending_stamp_, pending_err_, yaw_pd_command_;
    void processPendingBearing();
    double previous_world_bearing_, target_angular_velocity_, bearing_stamp_;
    struct YawSample { double stamp, yaw; };
    std::deque<YawSample> yaw_history_;
    void recordYawSample();
    bool interpolateYaw(double stamp, double& yaw) const;
    void resetBearingEstimator();
    void updateBearingEstimator(double err, double dt);
    double k_p_vz_, k_d_vz_, max_vz_, deadzone_vz_;
    double forward_velocity_, sprint_velocity_, sprint_time_;
    double data_timeout_, approach_area_threshold_, center_tolerance_, search_yaw_rate_;
    double prev_err_x_, prev_err_y_;
    static constexpr int ALIGN_STABLE_FRAMES_REQUIRED = 2;
    void updateTargetData();
    bool isTargetLost();
    bool isCentered() const;
    double computeYawRate(double err, double dt);
    double computeVz(double err, double dt);
};
#endif
