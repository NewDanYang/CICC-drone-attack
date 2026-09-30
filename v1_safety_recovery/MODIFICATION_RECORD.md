# TCEI Safety Boundary Recovery V1.0 modification record

Date: 2026-09-28
Scope: local source snapshot only; no formal simulation run.

## Modified official files

- src/mission_pkg/src/mavros_cnt.cpp
- src/mission_pkg/include/mavros_cnt.h
- src/mission_pkg/launch/llm_mission.launch

No other official files were modified.

## Behavior

- Added NORMAL/RECOVERING state in MavRosConnect.
- On first outer-boundary violation, compute the coordinate-wise nearest point in the inner envelope using safety/recovery_margin.
- During RECOVERING, construct a local MAVROS position target at the final publish layer. The shared current_cmd remains writable by Behavior Tree, GoTo, PlanningControl, and VisualServo.
- Release only after odometry remains inside the inner envelope for safety/recovery_confirm_time.
- On release, publish the latest current_cmd.

## Parameters

- safety/recovery_margin = 0.20 m
- safety/recovery_confirm_time = 0.50 s

Original boundary values are unchanged.

## Verification

- XML parse succeeded for llm_mission.launch.
- Recovery clamp and confirmation reset logic check passed.
- Full source comparison against pristine archive found no unexpected changed, missing, or added regular files.
- ROS/catkin compile was not available in the local Windows environment; no simulation was started.

Original SHA256: SHA256SUMS.original.txt
Patch: patches/safety_recovery_v1.0.diff
