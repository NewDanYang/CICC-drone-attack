# Research depth and timing package

This branch packages the completed research-only validation work. It does not replace the official cloud transform, publish flight setpoints, arm the vehicle, change simulator limits, or claim a canonical world-frame calibration.

## Included

- `depth/validator.py`: conservative cloud/odometry pairing, frame and extrinsic validation.
- `depth/planner_boundary.py`: research-namespace admission gate for fresh clouds.
- `depth/recovery_watchdog.py`: fail-closed offline lifecycle diagnostics.
- `timing/retiming.py`: offline cubic retiming and strict vector-limit checks.
- `tests/test_research_gates.py`: stdlib regression tests.

All outputs are diagnostic or research-only. Empty or missing observations remain unknown; they are never treated as free space.

## Verified outside this branch

The source workspace contains the full ROS shadow adapter and audit reports. The completed audits include moving-frame, recovery, frame-contract, planner-boundary and strict timing checks. The physical calibration runs restored the original sensor/configuration and ended grounded, disarmed and landed, but did not prove the signed Type7 basis or `odom1` to planner-world mapping. See the pull request for evidence paths and limitations.
