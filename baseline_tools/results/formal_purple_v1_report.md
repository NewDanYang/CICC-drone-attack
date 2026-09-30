# V1.0 Purple formal test

- Run ID: `20260928T002106_f9ef4b`
- Test date (UTC log): `2026-09-27`
- Source: remote `/home/ubuntu/tcei_baseline_tools/results/logs/20260928T002106_74b644_purple.jsonl`
- Mission input went through the existing `mission_once.py` natural-language path.
- No direct prebuilt `/mission_command` was injected.

## Result

- `bt_success=true`
- `mission_success=true`
- `end_status=completed`
- Total time: `113.702 s`
- ArUco detect time: `1.411 s`
- Balloon search time: `7.305 s`
- All six observed stages: `success`
- Safety boundary triggered: `false`
- Boundary recovery events: none

## Evidence

- First `/mission_command`: `2026-09-27T16:25:55.984+00:00`
- `Visual Servo Started`: `2026-09-27T16:27:26.745+00:00`
- `Sprint completed`: `2026-09-27T16:27:34.050+00:00`
- `Landed and disarmed`: `2026-09-27T16:27:49.676+00:00`
- `/mission_result`: `SUCCESS` at `2026-09-27T16:27:49.686+00:00`

The recovery state was not entered in this run, so this test confirms no regression and successful completion but does not independently exercise the RECOVERING branch.
