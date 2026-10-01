# V2 Patch 1 formal test — red

Date: 2026-10-01

## Build

- `catkin_make --pkg mission_pkg -j4`: passed.
- Initial runtime test exposed that the newly added plugin was not built because the package uses a non-`CONFIGURE_DEPENDS` CMake glob.
- Rebuilt with `catkin_make --force-cmake --pkg mission_pkg -j4`: passed.
- `wait_for_stable_position.so` was generated and `llm_mission_node` loaded 12 plugins.

## Mission

- Entry: official `mission_once.py` natural-language parser.
- Command: takeoff, cross_frame, detect_aruco, return_cross_frame, hit_balloon:red, land.
- Observer: `/home/ubuntu/tcei_baseline_tools/run_baseline.py --color red --no-launch-llm --timeout 300`.

## Result

- run_id: `20261001T161850_d96357`
- total_time: `283.693 s`
- mission_success: `false`
- bt_success: empty (no terminal `/mission_result` before observer timeout)
- end_status: `stuck`
- takeoff: success
- first cross frame: success
- ArUco: success (`1.807 s`)
- return cross frame: success
- hit balloon: incomplete
- land: incomplete
- safety boundary: triggered once
- boundary recovery confirmed: false
- failure reason: `checkArrival` showed no progress for 20 s while returning to `(0, 0, 0.5)`.

Raw JSONL and the captured CSV are in this directory.
