# CICC Drone Attack

This repository preserves the TCEI drone search-and-strike project in three separate layers.

## Contents

### `official_baseline/`

Original official ROS1 / PX4 / MAVROS / RflySim workspace snapshot used for the baseline runs. It includes the original `src/` tree and the official startup scripts:

- `official_baseline/catkin_ws/src/`
- `official_baseline/catkin_ws/sim_env_start.sh`
- `official_baseline/catkin_ws/kill_ros_pid.sh`

This copy is kept unchanged as the reference baseline.

### `baseline_tools/`

Independent observer-only baseline recorder:

- `run_baseline.py`
- `results/baseline_runs.csv`
- `results/logs/` with selected red, purple, blue baseline JSONL logs and the V1 purple formal-run log
- `results/formal_purple_v1_report.md`

The observer listens to ROS evidence and does not publish flight-control commands. Natural-language mission input remains on the official `mission_once.py` path.

### `v1_safety_recovery/`

V1 Safety Boundary Recovery overlay. Only these official source paths are changed by the overlay:

- `src/mission_pkg/src/mavros_cnt.cpp`
- `src/mission_pkg/include/mavros_cnt.h`
- `src/mission_pkg/launch/llm_mission.launch`

The overlay adds a `NORMAL` / `RECOVERING` state, an inward recovery point, and inner-boundary confirmation. The shared Behavior Tree command remains writable during recovery and is resumed after confirmation.

See `v1_safety_recovery/patches/safety_recovery_v1.0.diff` and the verification report for details.

## V1 parameters

```yaml
safety/recovery_margin: 0.20
safety/recovery_confirm_time: 0.50
```

The original safety bounds remain unchanged.

## Recorded V1 purple result

The first formal purple run after compiling `mission_pkg` completed successfully:

- `bt_success=true`
- `mission_success=true`
- total time: `113.702 s`
- safety boundary triggered: `false`

The run did not enter `RECOVERING`, so it confirms no regression and full-task completion but does not independently exercise the recovery branch.

## Restoration

The original V1 source files are preserved in `v1_safety_recovery/SHA256SUMS.original.txt` and the backup record. The local restoration helper is `v1_safety_recovery/restore_safety_recovery_v1.0.ps1`.
