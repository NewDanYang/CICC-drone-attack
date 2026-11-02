/******************************************************************************
 * @file       fm9g_locate.cpp
 * @brief      Fm9gLocate: hover while FM9G4B-V localises a scene target, then
 *             write its world position to the blackboard for GoTo/PlanningControl.
 *
 * @details    Perception happens in the FM9G scene bridge (mission_once.py
 *             process).  This node only (1) asks for a target on
 *             /fm9g/scene_request, (2) collects world-frame samples from
 *             /fm9g/target_world/<object_name>, (3) accepts when min_samples
 *             recent samples agree within max_spread, and (4) outputs their
 *             median.  It never generates a position by itself:
 *               - without fallback_pos, a timeout is a FAILURE (forward frame
 *                 pass: no preset coordinate may stand in for perception);
 *               - with fallback_pos (the official baseline's own waypoint, or a
 *                 position perceived earlier in the mission) it logs
 *                 FM9G_LOCATE_FALLBACK and returns that, so the mission is
 *                 never worse than the official behaviour.
 *
 *             Built as a plugin automatically by the CMake glob over
 *             src/nodes/perception (no CMakeLists change needed).
 *****************************************************************************/
#include "base/drone_action_node.h"

#include <geometry_msgs/PointStamped.h>
#include <std_msgs/String.h>

#include <algorithm>
#include <cmath>
#include <deque>
#include <sstream>

class Fm9gLocate : public DroneActionNode {
public:
    Fm9gLocate(const std::string& name, const NodeConfig& config)
        : DroneActionNode(name, config) {
        auto nh = mct->getROSHandle();
        request_pub_ = nh->advertise<std_msgs::String>("/fm9g/scene_request", 10);
    }

    static PortsList providedPorts() {
        return {
            InputPort<std::string>("object_name", "square_frame|pillar|aruco_marker|landing_pad"),
            InputPort<Position3D>("expected_pos", "可选: 期望位置, 用于剔除离群样本"),
            InputPort<double>("xy_tolerance", 1.0, "与 expected_pos 的水平容差(米)"),
            InputPort<double>("z_tolerance", 1.0, "与 expected_pos 的高度容差(米)"),
            InputPort<int>("min_samples", 3, "一致样本数"),
            InputPort<double>("max_spread", 0.3, "样本到中位数的最大水平距离(米)"),
            InputPort<double>("timeout", 15.0, "超时(秒)"),
            InputPort<Position3D>("fallback_pos", "可选: 超时后使用的位置(官方航点或先前感知结果)"),
            InputPort<bool>("ground_target", false, "地面目标: 输出高度取 fallback_pos.z 或当前高度"),
            OutputPort<Position3D>("position", "定位结果(世界系 ENU)"),
        };
    }

    NodeStatus onStart() override {
        auto name_res = getInput<std::string>("object_name");
        if (!name_res) throw RuntimeError("Fm9gLocate: missing object_name");
        object_ = name_res.value();
        has_expected_ = static_cast<bool>(getInput<Position3D>("expected_pos"));
        if (has_expected_) expected_ = getInput<Position3D>("expected_pos").value();
        xy_tol_ = getInput<double>("xy_tolerance").value();
        z_tol_ = getInput<double>("z_tolerance").value();
        min_samples_ = std::max(1, getInput<int>("min_samples").value());
        max_spread_ = getInput<double>("max_spread").value();
        timeout_ = getInput<double>("timeout").value();
        has_fallback_ = static_cast<bool>(getInput<Position3D>("fallback_pos"));
        if (has_fallback_) fallback_ = getInput<Position3D>("fallback_pos").value();
        ground_ = getInput<bool>("ground_target").value();

        samples_.clear();
        rejected_ = 0;
        have_last_stamp_ = false;
        start_ = ros::Time::now();
        std::ostringstream id;
        id << object_ << "_" << start_.toNSec();
        request_id_ = id.str();
        auto nh = mct->getROSHandle();
        sub_ = nh->subscribe("/fm9g/target_world/" + object_, 20, &Fm9gLocate::onSample, this);
        sendRequest("start");
        last_request_ = start_;
        ROS_INFO("[%s]: FM9G locate '%s' (min_samples=%d spread=%.2f timeout=%.1f fallback=%s)",
                 name().c_str(), object_.c_str(), min_samples_, max_spread_, timeout_,
                 has_fallback_ ? "yes" : "no");
        return NodeStatus::RUNNING;
    }

    NodeStatus onRunning() override {
        sendHoverCommand();
        ros::Time now = ros::Time::now();
        if ((now - last_request_).toSec() > 2.0) {   // idempotent re-send
            sendRequest("start");
            last_request_ = now;
        }
        Position3D result;
        if (tryAccept(result)) {
            finish();
            if (ground_) result.z = outputZ();
            setOutput("position", result);
            ROS_INFO("[%s]: FM9G_LOCATE_SUCCESS %s at (%.2f, %.2f, %.2f) from %zu samples (%d rejected) in %.1fs",
                     name().c_str(), object_.c_str(), result.x, result.y, result.z,
                     samples_.size(), rejected_, (now - start_).toSec());
            return NodeStatus::SUCCESS;
        }
        if ((now - start_).toSec() > timeout_) {
            finish();
            if (has_fallback_) {
                Position3D out = fallback_;
                if (ground_) out.z = outputZ();
                setOutput("position", out);
                ROS_WARN("[%s]: FM9G_LOCATE_FALLBACK %s after %.1fs (%zu samples, %d rejected) -> (%.2f, %.2f, %.2f)",
                         name().c_str(), object_.c_str(), timeout_, samples_.size(), rejected_,
                         out.x, out.y, out.z);
                return NodeStatus::SUCCESS;
            }
            ROS_ERROR("[%s]: FM9G_LOCATE_TIMEOUT %s after %.1fs (%zu samples, %d rejected)",
                      name().c_str(), object_.c_str(), timeout_, samples_.size(), rejected_);
            return NodeStatus::FAILURE;
        }
        ROS_INFO_THROTTLE(2.0, "[%s]: waiting for FM9G %s: %zu/%d samples, %d rejected",
                          name().c_str(), object_.c_str(), samples_.size(), min_samples_, rejected_);
        return NodeStatus::RUNNING;
    }

    void onHalted() override {
        finish();
        DroneActionNode::onHalted();
    }

private:
    void onSample(const geometry_msgs::PointStamped::ConstPtr& msg) {
        if (msg->header.stamp < start_) return;      // only frames captured after the request
        if (have_last_stamp_ && !(last_stamp_ < msg->header.stamp)) return;   // one sample per image
        last_stamp_ = msg->header.stamp;
        have_last_stamp_ = true;
        Position3D p(msg->point.x, msg->point.y, msg->point.z);
        if (has_expected_) {
            double dx = p.x - expected_.x, dy = p.y - expected_.y;
            if (std::hypot(dx, dy) > xy_tol_ || std::abs(p.z - expected_.z) > z_tol_) {
                ++rejected_;
                ROS_WARN_THROTTLE(2.0, "[%s]: FM9G sample out of range (%.2f, %.2f, %.2f)",
                                  name().c_str(), p.x, p.y, p.z);
                return;
            }
        }
        samples_.push_back(p);
        while (static_cast<int>(samples_.size()) > 2 * min_samples_) samples_.pop_front();
    }

    static double median(std::vector<double> v) {
        std::sort(v.begin(), v.end());
        size_t n = v.size();
        return n % 2 ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
    }

    bool tryAccept(Position3D& out) {
        if (static_cast<int>(samples_.size()) < min_samples_) return false;
        // newest min_samples must agree
        std::vector<double> xs, ys, zs;
        for (size_t i = samples_.size() - min_samples_; i < samples_.size(); ++i) {
            xs.push_back(samples_[i].x);
            ys.push_back(samples_[i].y);
            zs.push_back(samples_[i].z);
        }
        Position3D m(median(xs), median(ys), median(zs));
        for (size_t i = 0; i < xs.size(); ++i) {
            if (std::hypot(xs[i] - m.x, ys[i] - m.y) > max_spread_) return false;
        }
        out = m;
        return true;
    }

    double outputZ() const {
        return has_fallback_ ? fallback_.z : fcu_odom_ptr->pose.pose.position.z;
    }

    void sendRequest(const std::string& verb) {
        std_msgs::String msg;
        msg.data = verb + " " + object_ + " " + request_id_;
        request_pub_.publish(msg);
    }

    void finish() {
        if (sub_) {
            sendRequest("stop");
            sub_.shutdown();
        }
    }

    ros::Publisher request_pub_;
    ros::Subscriber sub_;
    std::string object_, request_id_;
    Position3D expected_, fallback_;
    bool has_expected_{false}, has_fallback_{false}, ground_{false};
    double xy_tol_{1.0}, z_tol_{1.0}, max_spread_{0.3}, timeout_{15.0};
    int min_samples_{3}, rejected_{0};
    std::deque<Position3D> samples_;
    ros::Time start_, last_request_, last_stamp_;
    bool have_last_stamp_{false};
};

BT_REGISTER_NODES(factory) {
    factory.registerNodeType<Fm9gLocate>("Fm9gLocate");
}
