#include "nodes/action/visual_servo.h"
#include "utils/pose_utils.h"
#include <algorithm>
#include <cmath>

VisualServo::VisualServo(const std::string& name, const NodeConfig& config)
    : DroneActionNode(name, config), current_state_(ALIGN), has_ever_received_data_(false), max_area_ratio_(0.0) {
    auto nh = mct->getROSHandle();
    nh->param<double>("cx", img_cx_, 320.0);
    nh->param<double>("cy", img_cy_, 240.0);
    nh->param<double>("fx", img_fx_, 320.0);
    nh->param<int>("img_w", img_w_, 640);
    nh->param<int>("img_h", img_h_, 480);
}

PortsList VisualServo::providedPorts() {
    return { InputPort<PixelTarget>("pixel_target", "像素目标"),
        InputPort<double>("k_p_yaw_rate", 0.003, ""), InputPort<double>("k_d_yaw_rate", 0.008, ""),
        InputPort<double>("max_yaw_rate", 0.5, ""), InputPort<double>("deadzone_yaw", 8.0, ""),
        InputPort<double>("yaw_feedforward_gain", 1.0, ""),
        InputPort<double>("k_p_vz", 0.002, ""), InputPort<double>("k_d_vz", 0.006, ""),
        InputPort<double>("max_vz", 0.3, ""), InputPort<double>("deadzone_vz", 10.0, ""),
        InputPort<double>("forward_velocity", 0.35, ""), InputPort<double>("sprint_velocity", 1.5, ""),
        InputPort<double>("sprint_time", 1.2, ""), InputPort<double>("data_timeout", 1.0, ""),
        InputPort<double>("approach_area_threshold", 0.08, ""), InputPort<double>("center_tolerance", 0.15, ""),
        InputPort<double>("search_yaw_rate", 0.3, ""), InputPort<std::string>("target_color", "", "") };
}

NodeStatus VisualServo::onStart() {
    k_p_yaw_rate_ = getInput<double>("k_p_yaw_rate").value();
    k_d_yaw_rate_ = getInput<double>("k_d_yaw_rate").value();
    max_yaw_rate_ = getInput<double>("max_yaw_rate").value();
    deadzone_yaw_ = getInput<double>("deadzone_yaw").value();
    yaw_feedforward_gain_ = getInput<double>("yaw_feedforward_gain").value();
    resetBearingEstimator();
    yaw_pd_command_ = 0.0;
    yaw_history_.clear();
    recordYawSample();
    k_p_vz_ = getInput<double>("k_p_vz").value();
    k_d_vz_ = getInput<double>("k_d_vz").value();
    max_vz_ = getInput<double>("max_vz").value();
    deadzone_vz_ = getInput<double>("deadzone_vz").value();
    forward_velocity_ = getInput<double>("forward_velocity").value();
    sprint_velocity_ = getInput<double>("sprint_velocity").value();
    sprint_time_ = getInput<double>("sprint_time").value();
    data_timeout_ = getInput<double>("data_timeout").value();
    approach_area_threshold_ = getInput<double>("approach_area_threshold").value();
    center_tolerance_ = getInput<double>("center_tolerance").value();
    search_yaw_rate_ = getInput<double>("search_yaw_rate").value();
    target_color_ = getInput<std::string>("target_color").value();
    current_state_ = ALIGN;
    has_ever_received_data_ = target_valid_ = derivative_ready_ = new_observation_ = false;
    search_anchor_active_ = false;
    sprint_aborted_ = close_encounter_pending_ = false;
    close_encounter_stamp_ = close_encounter_lost_at_ = ros::Time();
    last_observation_stamp_ = observation_dt_ = 0.0;
    yaw_command_ = vz_command_ = prev_err_x_ = prev_err_y_ = max_area_ratio_ = 0.0;
    align_stable_frames_ = 0;
    ROS_INFO("[%s]: Visual Servo Started (observation-clock PD)", name().c_str());
    return NodeStatus::RUNNING;
}

void VisualServo::updateTargetData() {
    new_observation_ = false;
    auto input = getInput<PixelTarget>("pixel_target");
    if (!input || !input.value().is_detected) {
        target_valid_ = false;
        resetBearingEstimator();
        return;
    }
    const auto target = input.value();
    const double age = ros::Time::now().toSec() - target.timestamp;
    if (!std::isfinite(target.timestamp) || target.timestamp <= 0.0 || age < 0.0 || age > data_timeout_ ||
        !std::isfinite(target.center_x) || !std::isfinite(target.center_y) ||
        !std::isfinite(target.width) || !std::isfinite(target.height)) {
        target_valid_ = false;
        resetBearingEstimator();
        return;
    }
    if (target.timestamp <= last_observation_stamp_) return;
    observation_dt_ = target.timestamp - last_observation_stamp_;
    if (!target_valid_ || observation_dt_ > data_timeout_) resetBearingEstimator();
    last_observation_stamp_ = target.timestamp;
    last_target_ = target;
    target_valid_ = has_ever_received_data_ = new_observation_ = true;
}

bool VisualServo::isTargetLost() {
    return !has_ever_received_data_ || !target_valid_ ||
        ros::Time::now().toSec() - last_observation_stamp_ > data_timeout_;
}

NodeStatus VisualServo::onRunning() {
    recordYawSample();
    updateTargetData();
    const auto now = ros::Time::now();
    if (current_state_ == SPRINTING) {
        if (isTargetLost() && !sprint_aborted_) {
            sprint_aborted_ = true;
            search_anchor_ = fcu_odom_ptr->pose.pose.position;
            search_base_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
            ROS_WARN("[%s]: SPRINT_ABORT target lost; holding until original deadline", name().c_str());
        }
        if (sprint_aborted_) {
            publishPosition(search_anchor_, search_base_yaw_);
        }
        if ((now - sprint_start_time_).toSec() >= sprint_time_) {
            sendHoverCommand();
            ROS_INFO("[%s]: SPRINT_END ATTEMPTED_UNVERIFIED aborted=%d; physical hit requires visual confirmation",
                name().c_str(), sprint_aborted_);
            return NodeStatus::SUCCESS;
        }
        if (sprint_aborted_) return NodeStatus::RUNNING;
    }
    if (isTargetLost()) {
        if (close_encounter_pending_ && target_color_ == "red" &&
            (!close_encounter_lost_at_.isZero() ||
             ((now - close_encounter_stamp_).toSec() >= 0.0 &&
              (now - close_encounter_stamp_).toSec() <= 1.0))) {
            if (close_encounter_lost_at_.isZero()) {
                close_encounter_lost_at_ = now;
                search_anchor_ = fcu_odom_ptr->pose.pose.position;
                search_base_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
                ROS_INFO("[%s]: CLOSE_ENCOUNTER_LOSS holding for reacquisition; outcome unverified", name().c_str());
            }
            publishPosition(search_anchor_, search_base_yaw_);
            if ((now - close_encounter_lost_at_).toSec() >= 0.6) {
                sendHoverCommand();
                ROS_INFO("[%s]: CLOSE_ENCOUNTER_LOSS ATTEMPTED_UNVERIFIED; physical burst requires external confirmation", name().c_str());
                return NodeStatus::SUCCESS;
            }
            return NodeStatus::RUNNING;
        }
        close_encounter_pending_ = false;
        close_encounter_lost_at_ = ros::Time();
        current_state_ = ALIGN;
        align_stable_frames_ = 0;
        derivative_ready_ = false;
        resetBearingEstimator();
        yaw_command_ = vz_command_ = 0.0;
        if (!search_anchor_active_) {
            search_anchor_ = fcu_odom_ptr->pose.pose.position;
            search_base_yaw_ = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
            search_start_time_ = now;
            search_anchor_active_ = true;
            ROS_INFO("[%s]: SEARCH_ANCHOR pos=(%.3f,%.3f,%.3f) yaw=%.3f", name().c_str(),
                search_anchor_.x, search_anchor_.y, search_anchor_.z, search_base_yaw_);
        }
        publishPosition(search_anchor_, search_base_yaw_ + search_yaw_rate_ * (now - search_start_time_).toSec());
        return NodeStatus::RUNNING;
    }
    if (!close_encounter_lost_at_.isZero()) {
        close_encounter_pending_ = false;
        current_state_ = ALIGN;
        align_stable_frames_ = 0;
        derivative_ready_ = false;
        ROS_INFO("[%s]: CLOSE_ENCOUNTER_REACQUIRED; resuming alignment", name().c_str());
    }
    search_anchor_active_ = false;
    close_encounter_lost_at_ = ros::Time();
    const double err_x = last_target_.center_x - img_cx_;
    const double err_y = last_target_.center_y - img_cy_;
    const double ratio = last_target_.area() / (static_cast<double>(img_w_) * img_h_);
    max_area_ratio_ = std::max(max_area_ratio_, ratio);
    if (new_observation_) {
        const auto& q = fcu_odom_ptr->pose.pose.orientation;
        const double q_norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
        const double heading = PoseUtils::getYawFromQuat(q);
        const double heading_error = std::abs(std::atan2(std::sin(heading - M_PI), std::cos(heading - M_PI)));
        close_encounter_pending_ = target_color_ == "red" && ratio >= 0.30 &&
            last_target_.center_x >= 0.0 && last_target_.center_x <= img_w_ &&
            last_target_.center_y >= 0.0 && last_target_.center_y <= img_h_ &&
            std::isfinite(q_norm) && std::abs(q_norm - 1.0) <= 0.01 &&
            std::isfinite(heading_error) && heading_error <= 0.45;
        if (close_encounter_pending_) {
            close_encounter_stamp_.fromSec(last_observation_stamp_);
            ROS_INFO("[%s]: CLOSE_ENCOUNTER_OBS color=%s stamp=%.6f area=%.4f box=(%.1f,%.1f,%.1f,%.1f) state=%d",
                name().c_str(), target_color_.c_str(), last_observation_stamp_, ratio,
                last_target_.center_x, last_target_.center_y, last_target_.width, last_target_.height,
                static_cast<int>(current_state_));
        }
        const double dt = derivative_ready_ ? observation_dt_ : 0.0;
        pending_stamp_ = last_observation_stamp_;
        pending_err_ = err_x;
        bearing_pending_ = true;
        processPendingBearing();
        yaw_command_ = computeYawRate(err_x, dt);
        vz_command_ = computeVz(err_y, dt);
        derivative_ready_ = true;
        ROS_INFO_THROTTLE(0.5, "[%s]: OBS stamp=%.6f age=%.3f dt=%.3f err=(%.1f,%.1f) area=%.4f yaw_rate=%.3f vz=%.3f target_world_rate=%.3f ff_gain=%.3f",
            name().c_str(), last_observation_stamp_, now.toSec() - last_observation_stamp_, dt,
            err_x, err_y, ratio, yaw_command_, vz_command_, target_angular_velocity_, yaw_feedforward_gain_);
    }
    if (!new_observation_ && bearing_pending_) {
        processPendingBearing();
        const double ff = !bearing_pending_ && std::isfinite(yaw_feedforward_gain_) ?
            std::clamp(yaw_feedforward_gain_ * target_angular_velocity_, -max_yaw_rate_, max_yaw_rate_) : 0.0;
        yaw_command_ = std::clamp(yaw_pd_command_ + ff, -max_yaw_rate_, max_yaw_rate_);
    }
    if (current_state_ == ALIGN) {
        publishVelocityWithYawRate(0, 0, vz_command_, yaw_command_);
        if (new_observation_) {
            align_stable_frames_ = isCentered() ? align_stable_frames_ + 1 : 0;
            if (align_stable_frames_ >= ALIGN_STABLE_FRAMES_REQUIRED) {
                current_state_ = APPROACHING;
                align_stable_frames_ = 0;
                ROS_INFO("[%s]: Aligned on two observations -> APPROACHING", name().c_str());
            }
        }
    } else if (current_state_ == APPROACHING) {
        const double align_ratio = std::max(0.0, 1.0 - std::abs(err_x) / (img_w_ * 0.3));
        double vx = forward_velocity_ * align_ratio;
        bool heading_blocked = false;
        if (target_color_ == "red" && ratio >= approach_area_threshold_) {
            const double yaw = PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation);
            const double error = std::abs(std::atan2(std::sin(yaw - M_PI), std::cos(yaw - M_PI)));
            heading_blocked = error > 0.45;
            if (heading_blocked) ROS_WARN_THROTTLE(0.5, "[%s]: Red sprint heading blocked: yaw=%.3f error=%.3f rad", name().c_str(), yaw, error);
        }
        // Re-align before advancing at every distance. A small target can leave
        // the center while approaching, well before the sprint-area threshold.
        if (!isCentered() || heading_blocked) vx = 0.0;
        publishVelocityWithYawRate(vx, 0, vz_command_, yaw_command_);
        if (std::abs(err_x) > img_w_ * center_tolerance_ * 3) {
            current_state_ = ALIGN;
            align_stable_frames_ = 0;
        } else if (new_observation_ && ratio >= approach_area_threshold_ && isCentered() && !heading_blocked) {
            current_state_ = SPRINTING;
            sprint_start_time_ = now;
            ROS_INFO("[%s]: SPRINT_START pos=(%.3f,%.3f,%.3f) yaw=%.3f err=(%.1f,%.1f) area=%.4f", name().c_str(),
                fcu_odom_ptr->pose.pose.position.x, fcu_odom_ptr->pose.pose.position.y,
                fcu_odom_ptr->pose.pose.position.z, PoseUtils::getYawFromQuat(fcu_odom_ptr->pose.pose.orientation), err_x, err_y, ratio);
        }
    } else {
        publishVelocityWithYawRate(sprint_velocity_, 0, vz_command_, yaw_command_);
    }
    return NodeStatus::RUNNING;
}

void VisualServo::resetBearingEstimator() {
    bearing_ready_ = bearing_pending_ = false;
    previous_world_bearing_ = target_angular_velocity_ = bearing_stamp_ = 0.0;
}

void VisualServo::processPendingBearing() {
    const double age = ros::Time::now().toSec() - pending_stamp_;
    double yaw;
    if (age < 0.0 || age > std::min(data_timeout_, 0.15)) {
        resetBearingEstimator();
        return;
    }
    if (!interpolateYaw(pending_stamp_, yaw)) return;
    const double dt = bearing_ready_ ? pending_stamp_ - bearing_stamp_ : 0.0;
    updateBearingEstimator(pending_err_, dt);
    bearing_pending_ = false;
    if (bearing_ready_) bearing_stamp_ = pending_stamp_;
}

void VisualServo::recordYawSample() {
    const double now = ros::Time::now().toSec();
    while (!yaw_history_.empty() && now - yaw_history_.front().stamp > 1.5) yaw_history_.pop_front();
    const double stamp = fcu_odom_ptr->header.stamp.toSec();
    const auto& q = fcu_odom_ptr->pose.pose.orientation;
    const double norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
    if (!std::isfinite(stamp) || stamp <= 0.0 || stamp > now || now - stamp > 0.15 ||
        !std::isfinite(q.x) || !std::isfinite(q.y) || !std::isfinite(q.z) || !std::isfinite(q.w) ||
        !std::isfinite(norm) || std::abs(norm - 1.0) > 0.01) return;
    if (!yaw_history_.empty() && stamp <= yaw_history_.back().stamp) return;
    const double yaw = PoseUtils::getYawFromQuat(q);
    if (!std::isfinite(yaw)) return;
    yaw_history_.push_back({stamp, yaw});
    while (yaw_history_.size() > 512) yaw_history_.pop_front();
}

bool VisualServo::interpolateYaw(double stamp, double& yaw) const {
    for (size_t i = 1; i < yaw_history_.size(); ++i) {
        const auto& a = yaw_history_[i - 1];
        const auto& b = yaw_history_[i];
        const double gap = b.stamp - a.stamp;
        if (a.stamp <= stamp && stamp <= b.stamp && gap <= 0.15) {
            const double delta = b.yaw - a.yaw;
            yaw = a.yaw + (stamp - a.stamp) / gap * std::atan2(std::sin(delta), std::cos(delta));
            return true;
        }
    }
    return false;
}

void VisualServo::updateBearingEstimator(double err, double dt) {
    double yaw;
    if (!std::isfinite(err) || !std::isfinite(img_fx_) || img_fx_ <= 0.0 ||
        !interpolateYaw(last_observation_stamp_, yaw)) {
        resetBearingEstimator();
        return;
    }
    const double bearing = yaw - std::atan2(err, img_fx_);
    if (bearing_ready_ && std::isfinite(dt) && dt > 1e-6 && dt <= data_timeout_) {
        const double delta = bearing - previous_world_bearing_;
        const double rate = std::clamp(std::atan2(std::sin(delta), std::cos(delta)) / dt,
            -max_yaw_rate_, max_yaw_rate_);
        target_angular_velocity_ += 0.35 * (rate - target_angular_velocity_);
    } else {
        target_angular_velocity_ = 0.0;
    }
    previous_world_bearing_ = bearing;
    bearing_ready_ = true;
}

double VisualServo::computeYawRate(double err, double dt) {
    const double adjusted = std::abs(err) > deadzone_yaw_ ? err - std::copysign(deadzone_yaw_, err) : 0.0;
    // The deadzone is also the controller's zero-command region.  Clearing
    // the derivative memory here prevents the first centered observation
    // from emitting a residual kick from the preceding large error.
    if (adjusted == 0.0) {
        prev_err_x_ = 0.0;
        yaw_pd_command_ = 0.0;
        const double feedforward = !bearing_pending_ && std::isfinite(yaw_feedforward_gain_)
            ? std::clamp(yaw_feedforward_gain_ * target_angular_velocity_, -max_yaw_rate_, max_yaw_rate_)
            : 0.0;
        return feedforward;
    }
    const double derivative = dt > 1e-6 ? (adjusted - prev_err_x_) / dt : 0.0;
    prev_err_x_ = adjusted;
    const double feedforward = !bearing_pending_ && std::isfinite(yaw_feedforward_gain_) ?
        std::clamp(yaw_feedforward_gain_ * target_angular_velocity_, -max_yaw_rate_, max_yaw_rate_) : 0.0;
    yaw_pd_command_ = -(k_p_yaw_rate_ * adjusted + k_d_yaw_rate_ * derivative);
    return std::clamp(yaw_pd_command_ + feedforward, -max_yaw_rate_, max_yaw_rate_);
}

double VisualServo::computeVz(double err, double dt) {
    const double adjusted = std::abs(err) > deadzone_vz_ ? err - std::copysign(deadzone_vz_, err) : 0.0;
    if (adjusted == 0.0) {
        prev_err_y_ = 0.0;
        return 0.0;
    }
    const double derivative = dt > 1e-6 ? (adjusted - prev_err_y_) / dt : 0.0;
    prev_err_y_ = adjusted;
    return std::clamp(-(k_p_vz_ * adjusted + k_d_vz_ * derivative), -max_vz_, max_vz_);
}

bool VisualServo::isCentered() const {
    return std::abs(last_target_.center_x - img_cx_) <= std::max(last_target_.width * center_tolerance_, deadzone_yaw_) &&
        std::abs(last_target_.center_y - img_cy_) <= std::max(last_target_.height * center_tolerance_, deadzone_vz_);
}

BT_REGISTER_NODES(factory) { factory.registerNodeType<VisualServo>("VisualServo"); }
