# Safety Boundary Recovery V1.0: static analysis

Source snapshot: `C:\Users\admin\tcei_baseline_work\official_source_20260927_225142`
Status: analysis only; no official source modified and no simulation started.

## Safety implementation

- `src/mission_pkg/src/mavros_cnt.cpp:66-86` loads `safety/enabled` and six bounds, then runs `cmdPublishLoop` every 0.02 s (50 Hz).
- `src/mission_pkg/src/mavros_cnt.cpp:182-239` checks `isWithinBoundary()`. On the first out-of-boundary sample it copies the current odometry position and yaw into `hover_pos_` and `hover_yaw_`, sets `hover_locked_`, and logs `DRONE OUT OF BOUNDARY! Triggering Hover Lock`.
- While outside, it creates a `mavros_msgs/PositionTarget` with `FRAME_LOCAL_NED`, ignores velocity/acceleration/yaw-rate fields, and sends only a position hold at the captured point. ENU odometry is converted as `NED x=-ENU y`, `NED y=ENU x`, `NED z=ENU z`, yaw plus pi/2.
- When odometry is inside all six inclusive limits, it immediately clears `hover_locked_` and logs `Drone returned to safe area. Hover lock released`.
- `src/mission_pkg/include/mavros_cnt.h:35-44,108-116` defines the bounds and hover state. There is no recovery target, margin, hysteresis, or safe-region confirmation timer.

## Control priority

Behavior-tree action nodes call `MavRosConnect::updateCommand()` and only replace the shared `current_cmd` cache. `cmdPublishLoop` is the single 50 Hz publisher. Its safety branch writes the hover command before the common publish block, so safety normally overrides GoTo, PlanningControl, and VisualServo while the odometry remains outside. There is no explicit control-owner state machine; arbitration is implemented by this last-writer loop.

## VisualServo / Sprint

- `src/mission_pkg/src/bt_ros.cpp:324-355` injects VisualServo parameters into the generated BT.
- `src/mission_pkg/launch/llm_mission.launch:95-104` sets `forward_velocity=1.0`, `sprint_velocity=1.5`, `sprint_time=1.2`, area threshold `0.08`.
- `src/mission_pkg/src/nodes/action/visual_servo.cpp:163-187` advances in APPROACHING and enters SPRINTING when target area reaches 8%.
- `visual_servo.cpp:195-217` commands body-NED `vx=1.5 m/s` for 1.2 s, keeps yaw/vz correction when target data is present, and then calls `sendHoverCommand()` and returns SUCCESS after the timer reaches 1.2 s.
- `src/mission_pkg/include/nodes/action/visual_servo.h:22-27` confirms ALIGN/APPROACHING/SPRINTING state machine.

## Baseline interpretation

The source fully explains the common purple/blue failure mechanism: if the sprint or another active command carries the aircraft just outside a strict bound, the safety loop captures that already-invalid position and repeatedly commands PX4 to hold it. The normal return GoTo command is overwritten on each 50 Hz safety cycle, and the lock can only release after the measured odometry re-enters the envelope. A fixed outside hover point therefore has no mechanism to move inward and can deadlock.

The exact direction of the blue excursion needs setpoint/odometry evidence. The source does show a coordinate-frame risk: VisualServo publishes body-NED velocity, while position commands use an explicit ENU-to-NED conversion (`NED x=-ENU y`, `NED y=ENU x`). That can explain a direction/sign-sensitive sprint excursion, but this static snapshot alone does not prove the blue trajectory without the recorded setpoints.

## Planned V1.0 scope

Only the safety recovery layer should change: add a configurable inward recovery margin and a small recovery state machine in `MavRosConnect`, keeping the existing mission, BT, planner, perception, and VisualServo parameters unchanged. Planned files are backed up with SHA256 before edits.
