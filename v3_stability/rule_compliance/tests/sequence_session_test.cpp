#include "../deploy/sequence_session.hpp"
#include <cassert>
#include <iostream>
#include <limits>

void testTelemetryHealth() {
    mission_sequence::TelemetryHealth h;
    assert(!h.stateFresh() && !h.odomFresh());
    h.state_received = h.state_stamp_valid = h.odom_received = h.odom_stamp_valid = true;
    h.position_finite = h.quaternion_finite = true;
    h.quaternion_norm_squared = 1.0;
    h.state_receive_age = h.state_source_age = 1.002;
    h.odom_receive_age = h.odom_source_age = 1.0;
    assert(h.stateFresh() && h.odomFresh());
    h.state_receive_age = 2.5;
    h.state_source_age = -2.5;
    assert(h.stateFresh());
    h.state_receive_age = 2.500001;
    assert(!h.stateFresh());
    h.state_receive_age = 0.0;
    h.state_source_age = 2.500001;
    assert(!h.stateFresh());
    h.state_stamp_valid = false;
    assert(h.stateFresh());
    h.state_received = false;
    assert(!h.stateFresh());
    h.state_received = true;
    h.odom_receive_age = 1.000001;
    assert(!h.odomFresh());
    h.odom_receive_age = 0.0;
    h.odom_source_age = -1.000001;
    assert(!h.odomFresh());
    h.odom_source_age = 0.0;
    h.odom_stamp_valid = false;
    assert(!h.odomFresh());
    h.odom_stamp_valid = true;
    h.position_finite = false;
    assert(!h.odomFresh());
    h.position_finite = true;
    h.quaternion_finite = false;
    assert(!h.odomFresh());
    h.quaternion_finite = true;
    h.quaternion_norm_squared = 0.0;
    assert(!h.odomFresh());
    h.quaternion_norm_squared = std::numeric_limits<double>::infinity();
    assert(!h.odomFresh());
    h.quaternion_norm_squared = 1.0;
    h.odom_source_age = std::numeric_limits<double>::quiet_NaN();
    assert(!h.odomFresh());
    h.state_receive_age = std::numeric_limits<double>::quiet_NaN();
    assert(!h.stateFresh());
    const auto detail = h.diagnostics(true, false, "AUTO.LAND");
    for (const auto* field : {"state_receive_age_s=", "state_source_age_s=", "odom_receive_age_s=",
                             "odom_source_age_s=", "position_finite=", "quaternion_finite=",
                             "quaternion_norm_squared=", "mode=AUTO.LAND"})
        assert(detail.find(field) != std::string::npos);
}

using mission_sequence::Request;
using mission_sequence::Session;

void testLandingParameters() {
    bool position_read = false, yaw_read = false;
    auto position = [&](const std::string& key, const std::string& fallback) {
        assert(key == "land/return_pos" && fallback == "0.0;0.0;0.5");
        position_read = true;
        return std::string("1.2;-0.4;0.7");
    };
    auto yaw = [&](const std::string& key, double fallback) {
        assert(key == "land/return_yaw" && fallback == 0.0);
        yaw_read = true;
        return 1.25;
    };
    assert(mission_sequence::landXml(position, yaw) ==
           "      <GoTo goal=\"1.2;-0.4;0.7\" yaw=\"1.250000\"/>\n      <Land/>\n");
    assert(position_read && yaw_read);
    assert(mission_sequence::landXml(
        [](const std::string&, const std::string& fallback) { return fallback; },
        [](const std::string&, double fallback) { return fallback; }) ==
        "      <GoTo goal=\"0.0;0.0;0.5\" yaw=\"0.000000\"/>\n      <Land/>\n");
}

void testPostFlightHoldPolicy() {
    struct Setpoint {
        double x, y, z, yaw;
        bool position_control;
    };
    const Setpoint takeoff_goal{0.1, -0.2, 1.0, 0.6, true};
    const Setpoint observed{0.11, -0.19, 0.814, 0.58, true};
    Setpoint cached = takeoff_goal;
    int captures = 0;
    auto hold_current = [&] { cached = observed; ++captures; };
    mission_sequence::holdAfterFlightCommand("takeoff", true, hold_current);
    assert(captures == 0);
    assert(cached.x == takeoff_goal.x && cached.y == takeoff_goal.y);
    assert(cached.z == 1.0 && cached.z != observed.z);
    assert(cached.yaw == takeoff_goal.yaw && cached.position_control);
    for (double altitude : {0.0, 0.9, 1.4}) {
        cached = {0.3, -0.5, altitude, -0.4, true};
        mission_sequence::holdAfterFlightCommand("takeoff", true, hold_current);
        assert(captures == 0 && cached.z == altitude && cached.yaw == -0.4);
        assert(std::isfinite(cached.x) && std::isfinite(cached.y) && std::isfinite(cached.z));
        assert(cached.position_control);
    }

    mission_sequence::holdAfterFlightCommand("takeoff", false, hold_current);
    assert(captures == 1 && cached.z == observed.z && cached.yaw == observed.yaw);
    for (const auto* command : {"cross_frame", "detect_aruco", "return_cross_frame",
                                "hit_balloon:red", "hit_balloon:purple", "hit_balloon:blue"}) {
        for (bool success : {false, true}) {
            cached = {2.0, 3.0, 4.0, -0.7, false};
            const int previous_captures = captures;
            mission_sequence::holdAfterFlightCommand(command, success, hold_current);
            assert(captures == previous_captures + 1 && cached.position_control);
            assert(cached.x == observed.x && cached.y == observed.y && cached.z == observed.z);
            assert(cached.yaw == observed.yaw);
        }
    }
}

void testIdleWatchdogPolicy() {
    using mission_sequence::idleRecoveryNeeded;
    Session s("epoch");
    assert(s.receive({"epoch", "flight", "reset", "", true}, true).accepted);
    assert(s.receive({"epoch", "flight", "takeoff", "takeoff"}, true).accepted);
    assert(!idleRecoveryNeeded(s.busy(), true, false, false, false, "MANUAL"));
    s.complete(true);
    s.recordTerminal("takeoff", "takeoff", "SUCCESS", "");
    assert(!idleRecoveryNeeded(s.busy(), true, true, true, true, "OFFBOARD"));
    assert(idleRecoveryNeeded(s.busy(), true, true, true, false, "OFFBOARD"));
    assert(idleRecoveryNeeded(s.busy(), true, false, false, false, "OFFBOARD"));
    assert(idleRecoveryNeeded(s.busy(), true, true, false, true, "OFFBOARD"));
    assert(idleRecoveryNeeded(s.busy(), true, true, true, true, "MANUAL"));
    assert(idleRecoveryNeeded(s.busy(), true, true, true, true, "AUTO.LAND"));
    assert(!idleRecoveryNeeded(s.busy(), false, false, false, false, "MANUAL"));
    assert(!s.observeState(false, false, false, "MANUAL"));
    assert(idleRecoveryNeeded(s.busy(), true, false, false, false, "MANUAL"));
    s.requireRecovery();
    assert(s.recoveryRequired());
    assert(s.receive({"epoch", "flight", "cross", "cross_frame"}).reason == "RECOVERY_REQUIRED");
    assert(s.observeState(true, true, false, "AUTO.LAND"));
    assert(!idleRecoveryNeeded(s.busy(), false, true, true, false, "AUTO.LAND"));
    assert(s.recoveryRequired());
}

void testObservedLandingState() {
    Session s("epoch");
    s.requireRecovery();
    assert(!s.observeState(false, true, false, "AUTO.LAND"));
    assert(s.receive({"epoch", "stale", "stale-reset", "", true}, false).reason == "RESET_REQUIRES_DISARMED");
    assert(!s.observeState(true, false, false, "AUTO.LAND"));
    assert(s.observeState(true, true, false, "AUTO.LAND"));
    assert(s.recoveryRequired());
    assert(s.receive({"epoch", "fresh", "reset", "", true}, true).accepted);
    s.recordTerminal("reset", "", "SUCCESS", "RESET");
    assert(s.observeState(true, true, false, "AUTO.LAND"));
    assert(!s.recoveryRequired());
    assert(s.receive({"epoch", "fresh", "takeoff", "takeoff"}, true).accepted);
    s.complete(true);
    s.recordTerminal("takeoff", "takeoff", "SUCCESS", "");
    assert(!s.observeState(true, true, true, "AUTO.LAND"));
    assert(s.recoveryRequired());
    assert(s.receive({"epoch", "fresh", "cross", "cross_frame"}).reason == "RECOVERY_REQUIRED");
    assert(s.observeState(true, true, false, "AUTO.LAND"));
    assert(s.recoveryRequired());
    assert(s.receive({"epoch", "fresh", "cross", "cross_frame"}, true).reason == "REJECTED");
    assert(s.outcomeReason("cross") == "RECOVERY_REQUIRED");
    assert(s.receive({"epoch", "next", "reset-next", "", true}, true).accepted);
    assert(s.receive({"epoch", "next", "cross-next", "cross_frame"}, true).reason == "NOT_AIRBORNE");
    assert(s.receive({"epoch", "next", "land-next", "land"}, true).reason == "ALREADY_LANDED");
    assert(!mission_sequence::telemetryHealthy(true, true, true, true, true, false, false, "AUTO.LAND"));
    assert(!mission_sequence::telemetryHealthy(true, true, true, true, false, false, false, "AUTO.LAND"));
    assert(mission_sequence::telemetryHealthy(true, true, false, true, true, false, false, "MANUAL"));
    assert(mission_sequence::telemetryHealthy(true, true, true, false, false, true, true, "AUTO.LAND"));
    assert(mission_sequence::telemetryHealthy(true, true, false, true, true, false, false, "AUTO.LAND"));
    assert(mission_sequence::telemetryHealthy(true, true, true, true, true, false, false, "MANUAL"));
    assert(!mission_sequence::telemetryHealthy(true, true, true, true, true, false, false, "AUTO.LAND"));
    assert(mission_sequence::telemetryHealthy(true, true, true, true, false, true, false, "AUTO.LAND"));
    assert(!mission_sequence::telemetryHealthy(true, true, true, true, false, false, false, "MANUAL"));
    assert(!mission_sequence::telemetryHealthy(true, true, true, true, false, false, false, "POSCTL"));
    assert(mission_sequence::telemetryHealthy(true, true, true, true, false, false, false, "OFFBOARD"));
}

int main() {
    testTelemetryHealth();
    testObservedLandingState();
    testIdleWatchdogPolicy();
    testLandingParameters();
    testPostFlightHoldPolicy();
    Session s("epoch-1");
    assert(s.receive({"old", "round1", "reset1", "", true}, true).reason == "STALE_EPOCH");
    assert(s.receive({"epoch-1", "round1", "reset-too-early", "", true}).reason == "RESET_REQUIRES_DISARMED");
    assert(s.receive({"epoch-1", "round1", "reset1", "", true}, true).accepted);
    s.recordTerminal("reset1", "", "SUCCESS", "RESET");
    auto reset_replay = s.receive({"epoch-1", "round1", "reset1", "", true});
    assert(reset_replay.replay && reset_replay.reason == "SUCCESS" && s.outcomeReason("reset1") == "RESET");
    assert(s.cancel("old", "round1", "cancel-old").reason == "STALE_EPOCH");
    assert(s.cancel("epoch-1", "wrong", "cancel-wrong").reason == "SESSION_NOT_READY");
    assert(s.cancel("epoch-1", "round1", "cancel-before-request").reason == "CANCELLED");
    assert(s.cancel("epoch-1", "round1", "cancel-before-request").reason == "CANCELLED");
    assert(s.receive({"epoch-1", "round1", "cancel-before-request", "takeoff"}, true).reason == "REJECTED");
    assert(s.outcomeReason("cancel-before-request") == "CANCELLED");
    assert(s.receive({"epoch-1", "round1", "cross-before-takeoff", "cross_frame"}).reason == "NOT_AIRBORNE");
    assert(s.receive({"epoch-1", "round1", "cross-before-takeoff", "cross_frame"}).reason == "REJECTED");
    assert(s.outcomeReason("cross-before-takeoff") == "NOT_AIRBORNE");
    assert(s.receive({"epoch-1", "round1", "take1", "takeoff"}, true).accepted);
    assert(s.receive({"epoch-1", "round1", "take1", "takeoff"}).replay);
    assert(s.receive({"epoch-1", "round1", "take1", "land"}).reason == "REQUEST_ID_CONFLICT");
    assert(s.receive({"epoch-1", "round2", "take1", "takeoff"}).reason == "REQUEST_ID_CONFLICT");
    assert(s.receive({"epoch-1", "round1", "take2", "takeoff"}).reason == "BUSY");
    assert(s.receive({"epoch-1", "round1", "take2", "takeoff"}).reason == "REJECTED");
    assert(s.outcomeReason("take2") == "BUSY");
    assert(!s.canAbort("round1", "wrong") && s.canAbort("round1", "take1"));
    assert(s.cancel("epoch-1", "round1", "take1").reason == "ABORT_REQUESTED");
    assert(s.cancel("epoch-1", "round1", "unrelated").reason == "CANCELLED");
    s.complete(true);
    s.recordTerminal("take1", "takeoff", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round1", "take1", "takeoff"}).reason == "SUCCESS");
    assert(s.cancel("epoch-1", "round1", "take1").reason == "REQUEST_ALREADY_DECIDED");
    assert(mission_sequence::telemetryHealthy(true, true, true, true, false, false, false, "OFFBOARD"));
    assert(!mission_sequence::telemetryHealthy(false, true, true, true, false, false, false, "OFFBOARD"));
    assert(!mission_sequence::telemetryHealthy(true, false, true, true, false, false, false, "OFFBOARD"));
    assert(!mission_sequence::telemetryHealthy(true, true, false, true, false, false, false, "OFFBOARD"));
    assert(!mission_sequence::telemetryHealthy(true, true, true, false, false, false, false, "OFFBOARD"));
    assert(mission_sequence::telemetryHealthy(true, true, false, true, true, false, false));
    assert(mission_sequence::telemetryHealthy(true, true, false, true, false, true, false));
    assert(mission_sequence::telemetryHealthy(true, true, false, false, false, true, true));
    assert(!mission_sequence::telemetryHealthy(false, true, false, false, false, true, true));
    assert(s.receive({"epoch-1", "round1", "return1", "return_cross_frame"}).reason == "MISSING_ARUCO");
    assert(s.receive({"epoch-1", "round1", "cross1", "cross_frame"}).accepted);
    s.complete(false, true, false);
    s.recordTerminal("cross1", "cross_frame", "FAILURE", "FAILED_TEST");
    assert(s.receive({"epoch-1", "round1", "cross1", "cross_frame"}).reason == "FAILURE");
    assert(s.outcomeReason("cross1") == "FAILED_TEST");
    assert(s.receive({"epoch-1", "round1", "cross2", "cross_frame"}).reason == "COMMAND_ALREADY_ATTEMPTED");
    assert(s.receive({"epoch-1", "round1", "balloon1", "hit_balloon:yellow"}).reason == "INVALID_COMMAND");
    assert(s.receive({"epoch-1", "round1", "land1", "land"}).accepted);
    s.complete(false);
    s.recordTerminal("land1", "land", "TIMEOUT", "AUTO_LAND_REQUESTED");
    s.requireRecovery();
    assert(s.recoveryRequired());
    assert(s.receive({"epoch-1", "round1", "land2", "land"}).reason == "RECOVERY_REQUIRED");
    assert(s.receive({"epoch-1", "round1", "cross3", "cross_frame"}).reason == "RECOVERY_REQUIRED");
    assert(s.receive({"epoch-1", "round1", "land1", "land"}).reason == "TIMEOUT");
    assert(s.receive({"epoch-1", "round1", "emergency1", "emergency_land"}).accepted);
    s.complete(false);
    s.recordTerminal("emergency1", "emergency_land", "FAILURE", "STILL_ARMED");
    assert(s.receive({"epoch-1", "round1", "emergency2", "emergency_land"}).accepted);
    s.complete(true);
    s.recordTerminal("emergency2", "emergency_land", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round1", "cross4", "cross_frame"}).reason == "RECOVERY_REQUIRED");
    assert(s.receive({"epoch-1", "round2", "reset-too-early-2", "", true}).reason == "RESET_REQUIRES_DISARMED");
    assert(s.receive({"epoch-1", "round2", "reset2", "", true}, true).accepted);
    s.recordTerminal("reset2", "", "SUCCESS", "RESET");
    assert(!s.recoveryRequired());
    assert(s.cancel("epoch-1", "round1", "old-session-id").reason == "SESSION_NOT_READY");
    assert(s.receive({"epoch-1", "round2", "cancel-before-request", "takeoff"}, true).reason == "REQUEST_ID_CONFLICT");
    assert(s.receive({"epoch-1", "round1", "take4", "takeoff"}).reason == "SESSION_NOT_READY");
    assert(s.receive({"epoch-1", "round1", "reset3", "", true}, true).reason == "SESSION_ID_REUSED");
    assert(s.receive({"epoch-1", "round2", "reset2", "", true}).reason == "SUCCESS");
    assert(s.receive({"epoch-1", "round2", "take2-1", "takeoff"}, true).accepted);
    s.complete(false);
    s.recordTerminal("take2-1", "takeoff", "FAILURE", "NOT_ARMED");
    s.requireRecovery();
    assert(s.receive({"epoch-1", "round2", "take2-2", "takeoff"}, true).reason == "RECOVERY_REQUIRED");
    assert(s.receive({"epoch-1", "round2", "emergency3", "emergency_land"}).accepted);
    s.complete(true);
    s.recordTerminal("emergency3", "emergency_land", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round3", "reset-round3", "", true}, true).accepted);
    s.recordTerminal("reset-round3", "", "SUCCESS", "RESET");
    assert(s.receive({"epoch-1", "round3", "take3", "takeoff"}, true).accepted);
    s.complete(true);
    s.recordTerminal("take3", "takeoff", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round3", "cross3-final", "cross_frame"}).accepted);
    s.complete(true, true, true);
    s.recordTerminal("cross3-final", "cross_frame", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round3", "aruco3", "detect_aruco"}).accepted);
    s.complete(true);
    s.recordTerminal("aruco3", "detect_aruco", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round3", "return3", "return_cross_frame"}).accepted);
    s.complete(true);
    s.recordTerminal("return3", "return_cross_frame", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round3", "hit3", "hit_balloon:red"}).accepted);
    s.complete(false);
    s.recordTerminal("hit3", "hit_balloon:red", "FAILURE", "");
    assert(s.receive({"epoch-1", "round3", "hit4", "hit_balloon:blue"}).reason == "COMMAND_ALREADY_ATTEMPTED");
    assert(s.receive({"epoch-1", "round3", "land3", "land"}).accepted);
    s.complete(true);
    s.recordTerminal("land3", "land", "SUCCESS", "");
    assert(s.receive({"epoch-1", "round3", "land3", "land"}).reason == "SUCCESS");
    std::cout << "sequence session transitions passed\n";
}
