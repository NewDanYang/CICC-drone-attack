#pragma once

#include <cmath>
#include <sstream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

namespace mission_sequence {

struct Request {
    std::string epoch;
    std::string session;
    std::string id;
    std::string command;
    bool reset = false;
};

struct Decision {
    bool accepted;
    std::string reason;
    bool replay = false;
};

inline bool telemetryHealthy(bool state_fresh, bool connected, bool armed,
                             bool odom_fresh, bool takeoff, bool landing, bool emergency_landing,
                             const std::string& mode = "") {
    return state_fresh && connected && (takeoff || landing || armed) &&
           (landing || !armed || mode != "AUTO.LAND") &&
           (takeoff || landing || !armed || mode == "OFFBOARD") &&
           (emergency_landing || odom_fresh);
}

inline bool idleRecoveryNeeded(bool busy, bool last_known_armed, bool state_fresh,
                               bool connected, bool odom_fresh, const std::string& mode) {
    return !busy && last_known_armed &&
           !telemetryHealthy(state_fresh, connected, last_known_armed, odom_fresh,
                             false, false, false, mode);
}

template <typename HoldCurrent>
void holdAfterFlightCommand(const std::string& command, bool success, HoldCurrent hold_current) {
    // Takeoff publishes its goal and yaw before reporting success; retain that position command.
    if (command != "takeoff" || !success) hold_current();
}

template <typename GetString, typename GetDouble>
std::string landXml(GetString get_string, GetDouble get_double) {
    const auto position = get_string("land/return_pos", "0.0;0.0;0.5");
    const auto yaw = std::to_string(get_double("land/return_yaw", 0.0));
    return "      <GoTo goal=\"" + position + "\" yaw=\"" + yaw + "\"/>\n"
           "      <Land/>\n";
}

struct TelemetryHealth {
    bool state_received = false, state_stamp_valid = false;
    bool odom_received = false, odom_stamp_valid = false;
    double state_receive_age = 0.0, state_source_age = 0.0;
    double odom_receive_age = 0.0, odom_source_age = 0.0;
    bool position_finite = false, quaternion_finite = false;
    double quaternion_norm_squared = 0.0;

    bool stateFresh() const {
        return state_received && std::isfinite(state_receive_age) && state_receive_age >= 0.0 &&
            state_receive_age <= 2.5 && (!state_stamp_valid ||
            (std::isfinite(state_source_age) && std::abs(state_source_age) <= 2.5));
    }
    bool odomFresh() const {
        return odom_received && odom_stamp_valid && std::isfinite(odom_receive_age) &&
            odom_receive_age >= 0.0 && odom_receive_age <= 1.0 &&
            std::isfinite(odom_source_age) && std::abs(odom_source_age) <= 1.0 &&
            position_finite && quaternion_finite && std::isfinite(quaternion_norm_squared) &&
            std::abs(quaternion_norm_squared - 1.0) < 0.1;
    }
    std::string diagnostics(bool connected, bool armed, const std::string& mode) const {
        std::ostringstream out;
        out << "state_fresh=" << stateFresh() << " state_received=" << state_received
            << " state_receive_age_s=" << state_receive_age
            << " state_stamp_valid=" << state_stamp_valid << " state_source_age_s=" << state_source_age
            << " state_limit_s=2.5 connected=" << connected << " armed=" << armed << " mode=" << mode
            << " odom_fresh=" << odomFresh() << " odom_received=" << odom_received
            << " odom_receive_age_s=" << odom_receive_age
            << " odom_stamp_valid=" << odom_stamp_valid << " odom_source_age_s=" << odom_source_age
            << " odom_limit_s=1 position_finite=" << position_finite
            << " quaternion_finite=" << quaternion_finite
            << " quaternion_norm_squared=" << quaternion_norm_squared;
        return out.str();
    }
};

class Session {
public:
    explicit Session(std::string epoch) : epoch_(std::move(epoch)) {}

    Decision replay(const Request& request) const {
        if (request.epoch != epoch_) return {false, "STALE_EPOCH"};
        if (request.session.empty() || request.id.empty()) return {false, "MISSING_ID"};
        auto prior = requests_.find(request.id);
        if (prior == requests_.end()) return {false, "NEW_REQUEST"};
        if (prior->second.status == "REJECTED" && prior->second.reason == "CANCELLED" &&
            prior->second.session == request.session) return {false, "REJECTED", true};
        if (prior->second.session != request.session || prior->second.command != request.command ||
            prior->second.reset != request.reset) return {false, "REQUEST_ID_CONFLICT"};
        return {prior->second.status != "REJECTED",
                prior->second.status.empty() ? "ACCEPTED" : prior->second.status, true};
    }

    Decision cancel(const std::string& epoch, const std::string& session, const std::string& id) {
        if (epoch != epoch_) return {false, "STALE_EPOCH"};
        if (session.empty() || id.empty() || session != session_) return {false, "SESSION_NOT_READY"};
        if (canAbort(session, id)) return {true, "ABORT_REQUESTED"};
        auto prior = requests_.find(id);
        if (prior != requests_.end())
            return {false, prior->second.status == "REJECTED" && prior->second.reason == "CANCELLED" ?
                "CANCELLED" : "REQUEST_ALREADY_DECIDED"};
        requests_.emplace(id, Outcome{session, "", false, "REJECTED", "CANCELLED"});
        return {true, "CANCELLED"};
    }

    Decision receive(const Request& request, bool disarmed = false) {
        auto prior = replay(request);
        if (prior.reason != "NEW_REQUEST") return prior;
        if (busy_) return rejectDecision(request, "BUSY");
        if (request.reset) {
            if (!request.command.empty()) return rejectDecision(request, "INVALID_RESET");
            if (!disarmed) return rejectDecision(request, "RESET_REQUIRES_DISARMED");
            if (sessions_.count(request.session)) return rejectDecision(request, "SESSION_ID_REUSED");
            session_ = request.session;
            sessions_.insert(session_);
            frame_ready_ = false;
            planning_ready_ = false;
            completed_.clear();
            attempted_.clear();
            last_id_.clear();
            last_command_.clear();
            last_status_.clear();
            last_reason_.clear();
            airborne_ = false;
            recovery_required_ = false;
            requests_.emplace(request.id, Outcome{request.session, request.command, true, "", ""});
            return {true, "RESET"};
        }
        if (request.session != session_ || session_.empty()) return rejectDecision(request, "SESSION_NOT_READY");
        if (request.command != "takeoff" && request.command != "cross_frame" &&
            request.command != "detect_aruco" && request.command != "return_cross_frame" &&
            request.command != "land" && request.command != "emergency_land" &&
            request.command != "hit_balloon:red" && request.command != "hit_balloon:purple" &&
            request.command != "hit_balloon:blue")
            return rejectDecision(request, "INVALID_COMMAND");
        if (recovery_required_ && request.command != "emergency_land")
            return rejectDecision(request, "RECOVERY_REQUIRED");
        const std::string family = request.command.compare(0, 12, "hit_balloon:") == 0
            ? "hit_balloon" : request.command;
        if (family != "emergency_land" && attempted_.count(family))
            return rejectDecision(request, "COMMAND_ALREADY_ATTEMPTED");
        if (request.command == "takeoff" && (airborne_ || !disarmed))
            return rejectDecision(request, "TAKEOFF_REQUIRES_DISARMED");
        if (request.command != "takeoff" && request.command != "land" &&
            request.command != "emergency_land" && !airborne_)
            return rejectDecision(request, "NOT_AIRBORNE");
        if (request.command == "land" && !airborne_ && disarmed)
            return rejectDecision(request, "ALREADY_LANDED");
        if (request.command == "emergency_land" && !airborne_ && disarmed && !recovery_required_)
            return rejectDecision(request, "ALREADY_LANDED");
        if (request.command == "detect_aruco" && !completed_.count("cross_frame"))
            return rejectDecision(request, "MISSING_CROSS_FRAME");
        if (request.command == "return_cross_frame" && !completed_.count("detect_aruco"))
            return rejectDecision(request, "MISSING_ARUCO");
        if (request.command.compare(0, 12, "hit_balloon:") == 0 &&
            !completed_.count("return_cross_frame"))
            return rejectDecision(request, "MISSING_RETURN_CROSS_FRAME");
        if (request.command == "return_cross_frame" && (!frame_ready_ || !planning_ready_))
            return rejectDecision(request, "MISSING_FRAME_PLAN");
        requests_.emplace(request.id, Outcome{request.session, request.command, false, "", ""});
        attempted_.insert(family);
        busy_ = true;
        active_id_ = request.id;
        active_command_ = request.command;
        return {true, "ACCEPTED"};
    }

    void reject(const Request& request, const std::string& reason) {
        requests_.emplace(request.id, Outcome{request.session, request.command, request.reset,
                                              "REJECTED", reason});
    }
    Decision rejectDecision(const Request& request, const std::string& reason) {
        reject(request, reason);
        return {false, reason};
    }
    bool canAbort(const std::string& session, const std::string& id) const {
        return busy_ && session == session_ && id == active_id_;
    }
    void complete(bool success, bool frame_available = false, bool plan_available = false) {
        if (!busy_) throw std::logic_error("no active command");
        if (active_command_ == "cross_frame") {
            frame_ready_ = success && frame_available;
            planning_ready_ = success && plan_available;
        }
        if (success) {
            completed_.insert(active_command_);
            if (active_command_ == "takeoff") airborne_ = true;
            if (active_command_ == "land" || active_command_ == "emergency_land") airborne_ = false;
        }
        busy_ = false;
        active_id_.clear();
        active_command_.clear();
    }
    void requireRecovery() { recovery_required_ = true; }
    bool observeState(bool fresh, bool connected, bool armed, const std::string& mode) {
        const bool disarmed = fresh && connected && !armed;
        if (disarmed && !busy_) airborne_ = false;
        if (fresh && armed && mode == "AUTO.LAND") recovery_required_ = true;
        return disarmed;
    }
    bool recoveryRequired() const { return recovery_required_; }
    const std::string& epoch() const { return epoch_; }
    const std::string& session() const { return session_; }
    bool busy() const { return busy_; }
    const std::string& activeId() const { return active_id_; }
    const std::string& activeCommand() const { return active_command_; }
    const std::string& lastId() const { return last_id_; }
    const std::string& lastCommand() const { return last_command_; }
    const std::string& lastStatus() const { return last_status_; }
    const std::string& lastReason() const { return last_reason_; }
    std::string outcomeReason(const std::string& id) const { return requests_.at(id).reason; }
    void recordTerminal(const std::string& id, const std::string& command,
                        const std::string& status, const std::string& reason) {
        auto& outcome = requests_.at(id);
        outcome.status = status;
        outcome.reason = reason;
        last_id_ = id;
        last_command_ = command;
        last_status_ = status;
        last_reason_ = reason;
    }

private:
    struct Outcome {
        std::string session, command;
        bool reset;
        std::string status, reason;
    };
    std::string epoch_, session_, active_id_, active_command_;
    std::string last_id_, last_command_, last_status_, last_reason_;
    std::map<std::string, Outcome> requests_;
    std::set<std::string> sessions_, completed_, attempted_;
    bool busy_ = false;
    bool airborne_ = false;
    bool frame_ready_ = false;
    bool planning_ready_ = false;
    bool recovery_required_ = false;
};

} // namespace mission_sequence
