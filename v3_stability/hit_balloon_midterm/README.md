# Hit-balloon midterm implementation package

This directory records the reproducible code and evidence index for the 2026-10-11 midterm checkpoint.

## Included changes

- `patches/patch_planned_navigation.py`: waits for a planner subscriber and fresh trajectory before accepting a goal; holds position while the planner is stalled.
- `patches/patch_return_view.py`: turns toward the return goal and refreshes the registered cloud before publishing the return goal.
- `patches/patch_landing_settle.py`: requires position, fresh odometry, and speed to remain within limits before `AUTO.LAND`.
- `patches/patch_visual_sprint_alignment_v3.py`: gates sprinting on target centering.
- `patches/patch_visual_yaw_direction_v1.py`: applies the simulator camera yaw sign convention.
- `patches/patch_bounded_visual_search_v3.py`: bounds cumulative target-loss search time so the vehicle does not rotate indefinitely.
- `aruco/aruco_detect_node.py`: the validated headless ArUco detector snapshot used by the latest trials.
- `tools/run_hit_regression.sh`, `tools/analyze_hit_trial.py`, and `tools/check_flight_map.py`: repeatable trial capture and offline evidence checks.

## Deployment order

Apply on a disarmed vehicle, with a backup before every source mutation:

1. planner and landing patches;
2. return-view patch;
3. visual sprint alignment;
4. yaw direction;
5. bounded visual search;
6. rebuild `mission_pkg` after C++ patches and restart the mission node.

The patch scripts fail closed when their expected source shape is absent or the patch is already present. They are deployment helpers, not a substitute for a code review.

## Current evidence boundary

The accompanying report records the tested scope. ArUco detection, outbound/return navigation, and settling were validated in simulation. One red-balloon trial was confirmed popped by the operator. Purple-balloon trials remained unsuccessful, and `Mission result: SUCCESS` is not treated as proof of a hit because the behavior tree still contains `ForceSuccess`.

Server paths in the report are evidence references only; credentials and runtime bags stay outside the repository.

