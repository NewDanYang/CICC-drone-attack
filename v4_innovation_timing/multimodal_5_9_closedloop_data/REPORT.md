# FM9G 真实闭环数据采集（5.9）

本目录只交付六局原始数据，不对命中率、对齐率或闭环性能做判断。采集顺序为 `red, purple, blue, red, purple, blue`；每局前后完整重启仿真环境。

## 六局路径

|局次|颜色|正式试验目录|multimodal_v2 审计目录|audit.jsonl|images/|rosout|
|---:|---|---|---|---:|---:|---|
|1|red|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200152_red_A0`|`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261101T120210_feab58`|1|1|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200152_red_A0/logs/20261101T200156_199375_red.jsonl`|
|2|purple|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200536_purple_A0`|`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261101T120552_4a16b7`|1|1|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200536_purple_A0/logs/20261101T200541_0264fe_purple.jsonl`|
|3|blue|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200928_blue_A0`|`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261101T120951_7efdde`|1|1|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200928_blue_A0/logs/20261101T200933_b93f57_blue.jsonl`|
|4|red|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201333_red_A0`|`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261101T121350_649221`|1|1|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201333_red_A0/logs/20261101T201338_565286_red.jsonl`|
|5|purple|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201714_purple_A0`|`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261101T121738_a2ac43`|1|1|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201714_purple_A0/logs/20261101T201719_fcd333_purple.jsonl`|
|6|blue|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T202112_blue_A0`|`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261101T122134_bba2ae`|1|1|`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T202112_blue_A0/logs/20261101T202116_f5c1ad_blue.jsonl`|

服务器清单原文见 [`server_manifest.tsv`](evidence/server_manifest.tsv)。六局的 `audit.jsonl` 和 `images/` 均存在（清单中的 `1/1`）。每局重启日志及 `/mavros/state`、起点里程计采样见 [`restarts/`](evidence/restarts/)。

## MD5

冻结视觉侧和 5.5 修复后的感知 runtime 在采集前后保持相同。逐局记录见 [`md5_checks.tsv`](evidence/md5_checks.tsv)；原始核对见 [`md5_preflight.txt`](evidence/md5_preflight.txt) 与 [`md5_final.txt`](evidence/md5_final.txt)。

## `observer.out` 原文

### 01_red_observer.out

```text
run_id=20261101T200156_f5d88a
natural_language_task=飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击红色气球，完成后就回到起点并降落；
v21_telemetry_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200152_red_A0/20261101T200156_199375_red_telemetry.jsonl
v21_planning_summary=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200152_red_A0/planning_runs.csv
Observer ready: waiting for first /mission_command; timing starts automatically.
{
  "run_id": "20261101T200156_f5d88a",
  "target_color": "red",
  "start_time": "2026-11-01T12:02:21.481+00:00",
  "end_time": "2026-11-01T12:04:24.098+00:00",
  "total_time": "122.617",
  "elapsed_time": "122.617",
  "bt_success": "true",
  "mission_success": "false",
  "end_status": "completed",
  "takeoff_status": "success",
  "cross_frame_status": "success",
  "detect_aruco_status": "success",
  "return_cross_frame_status": "success",
  "hit_balloon_status": "",
  "land_status": "success",
  "aruco_detect_time": "0.154",
  "balloon_search_time": "",
  "failure_stage": "hit_balloon",
  "failure_reason": "",
  "safety_boundary_triggered": "false",
  "boundary_first_time": "",
  "boundary_first_position": "",
  "boundary_violation_count": "0",
  "boundary_recovered": "",
  "notes": "mission_command received as text; SUCCESS received while stages were unobserved: hit_balloon; bt_planning_controls=[{\"goal\":\"{frame_center}\",\"offset_z\":\"1.000000\",\"kind\":\"frame_outbound\"},{\"goal\":\"{frame_center}\",\"offset_z\":\"\",\"kind\":\"frame_return\"},{\"goal\":\"4.3;1.0;0.7\",\"offset_z\":\"\",\"kind\":\"other\"}]; rosout_events_logged; setpoint_samples=6132; target_detection_messages=720"
}
csv=/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
raw_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200152_red_A0/logs/20261101T200156_199375_red.jsonl
```

### 02_purple_observer.out

```text
run_id=20261101T200541_847ce8
natural_language_task=飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击紫色气球，完成后就回到起点并降落；
v21_telemetry_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200536_purple_A0/20261101T200541_0264fe_purple_telemetry.jsonl
v21_planning_summary=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200536_purple_A0/planning_runs.csv
Observer ready: waiting for first /mission_command; timing starts automatically.
{
  "run_id": "20261101T200541_847ce8",
  "target_color": "purple",
  "start_time": "2026-11-01T12:06:02.428+00:00",
  "end_time": "2026-11-01T12:08:16.820+00:00",
  "total_time": "134.393",
  "elapsed_time": "134.393",
  "bt_success": "true",
  "mission_success": "false",
  "end_status": "completed",
  "takeoff_status": "success",
  "cross_frame_status": "success",
  "detect_aruco_status": "success",
  "return_cross_frame_status": "success",
  "hit_balloon_status": "",
  "land_status": "success",
  "aruco_detect_time": "0.103",
  "balloon_search_time": "",
  "failure_stage": "hit_balloon",
  "failure_reason": "",
  "safety_boundary_triggered": "true",
  "boundary_first_time": "2026-11-01T12:07:57.170+00:00",
  "boundary_first_position": "",
  "boundary_violation_count": "1",
  "boundary_recovered": "true",
  "notes": "mission_command received as text; SUCCESS received while stages were unobserved: hit_balloon; bt_planning_controls=[{\"goal\":\"{frame_center}\",\"offset_z\":\"1.000000\",\"kind\":\"frame_outbound\"},{\"goal\":\"{frame_center}\",\"offset_z\":\"\",\"kind\":\"frame_return\"},{\"goal\":\"4.3;-2.0;0.7\",\"offset_z\":\"\",\"kind\":\"other\"}]; rosout_events_logged; setpoint_samples=6719; target_detection_messages=698"
}
csv=/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
raw_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200536_purple_A0/logs/20261101T200541_0264fe_purple.jsonl
```

### 03_blue_observer.out

```text
run_id=20261101T200933_444a5c
natural_language_task=飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击蓝色气球，完成后就回到起点并降落；
v21_telemetry_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200928_blue_A0/20261101T200933_b93f57_blue_telemetry.jsonl
v21_planning_summary=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200928_blue_A0/planning_runs.csv
Observer ready: waiting for first /mission_command; timing starts automatically.
{
  "run_id": "20261101T200933_444a5c",
  "target_color": "blue",
  "start_time": "2026-11-01T12:10:01.179+00:00",
  "end_time": "2026-11-01T12:12:21.583+00:00",
  "total_time": "140.404",
  "elapsed_time": "140.404",
  "bt_success": "true",
  "mission_success": "false",
  "end_status": "completed",
  "takeoff_status": "success",
  "cross_frame_status": "success",
  "detect_aruco_status": "success",
  "return_cross_frame_status": "success",
  "hit_balloon_status": "",
  "land_status": "success",
  "aruco_detect_time": "0.150",
  "balloon_search_time": "",
  "failure_stage": "hit_balloon",
  "failure_reason": "",
  "safety_boundary_triggered": "false",
  "boundary_first_time": "",
  "boundary_first_position": "",
  "boundary_violation_count": "0",
  "boundary_recovered": "",
  "notes": "mission_command received as text; SUCCESS received while stages were unobserved: hit_balloon; bt_planning_controls=[{\"goal\":\"{frame_center}\",\"offset_z\":\"1.000000\",\"kind\":\"frame_outbound\"},{\"goal\":\"{frame_center}\",\"offset_z\":\"\",\"kind\":\"frame_return\"},{\"goal\":\"5.3;1.0;0.7\",\"offset_z\":\"\",\"kind\":\"other\"}]; rosout_events_logged; setpoint_samples=7023; target_detection_messages=776"
}
csv=/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
raw_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T200928_blue_A0/logs/20261101T200933_b93f57_blue.jsonl
```

### 04_red_observer.out

```text
run_id=20261101T201338_d80336
natural_language_task=飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击红色气球，完成后就回到起点并降落；
v21_telemetry_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201333_red_A0/20261101T201338_565286_red_telemetry.jsonl
v21_planning_summary=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201333_red_A0/planning_runs.csv
Observer ready: waiting for first /mission_command; timing starts automatically.
{
  "run_id": "20261101T201338_d80336",
  "target_color": "red",
  "start_time": "2026-11-01T12:14:00.639+00:00",
  "end_time": "2026-11-01T12:16:02.382+00:00",
  "total_time": "121.743",
  "elapsed_time": "121.743",
  "bt_success": "true",
  "mission_success": "false",
  "end_status": "completed",
  "takeoff_status": "success",
  "cross_frame_status": "success",
  "detect_aruco_status": "success",
  "return_cross_frame_status": "success",
  "hit_balloon_status": "",
  "land_status": "success",
  "aruco_detect_time": "0.107",
  "balloon_search_time": "",
  "failure_stage": "hit_balloon",
  "failure_reason": "",
  "safety_boundary_triggered": "false",
  "boundary_first_time": "",
  "boundary_first_position": "",
  "boundary_violation_count": "0",
  "boundary_recovered": "",
  "notes": "mission_command received as text; SUCCESS received while stages were unobserved: hit_balloon; bt_planning_controls=[{\"goal\":\"{frame_center}\",\"offset_z\":\"1.000000\",\"kind\":\"frame_outbound\"},{\"goal\":\"{frame_center}\",\"offset_z\":\"\",\"kind\":\"frame_return\"},{\"goal\":\"4.3;1.0;0.7\",\"offset_z\":\"\",\"kind\":\"other\"}]; rosout_events_logged; setpoint_samples=6090; target_detection_messages=716"
}
csv=/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
raw_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201333_red_A0/logs/20261101T201338_565286_red.jsonl
```

### 05_purple_observer.out

```text
run_id=20261101T201719_d7d7b3
natural_language_task=飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击紫色气球，完成后就回到起点并降落；
v21_telemetry_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201714_purple_A0/20261101T201719_fcd333_purple_telemetry.jsonl
v21_planning_summary=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201714_purple_A0/planning_runs.csv
Observer ready: waiting for first /mission_command; timing starts automatically.
{
  "run_id": "20261101T201719_d7d7b3",
  "target_color": "purple",
  "start_time": "2026-11-01T12:17:48.921+00:00",
  "end_time": "2026-11-01T12:20:00.190+00:00",
  "total_time": "131.269",
  "elapsed_time": "131.269",
  "bt_success": "true",
  "mission_success": "false",
  "end_status": "completed",
  "takeoff_status": "success",
  "cross_frame_status": "success",
  "detect_aruco_status": "success",
  "return_cross_frame_status": "success",
  "hit_balloon_status": "",
  "land_status": "success",
  "aruco_detect_time": "0.330",
  "balloon_search_time": "",
  "failure_stage": "hit_balloon",
  "failure_reason": "",
  "safety_boundary_triggered": "true",
  "boundary_first_time": "2026-11-01T12:19:13.610+00:00",
  "boundary_first_position": "",
  "boundary_violation_count": "2",
  "boundary_recovered": "true",
  "notes": "mission_command received as text; SUCCESS received while stages were unobserved: hit_balloon; bt_planning_controls=[{\"goal\":\"{frame_center}\",\"offset_z\":\"1.000000\",\"kind\":\"frame_outbound\"},{\"goal\":\"{frame_center}\",\"offset_z\":\"\",\"kind\":\"frame_return\"},{\"goal\":\"4.3;-2.0;0.7\",\"offset_z\":\"\",\"kind\":\"other\"}]; rosout_events_logged; setpoint_samples=6570; target_detection_messages=921"
}
csv=/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
raw_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T201714_purple_A0/logs/20261101T201719_fcd333_purple.jsonl
```

### 06_blue_observer.out

```text
run_id=20261101T202116_1f9fd3
natural_language_task=飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击蓝色气球，完成后就回到起点并降落；
v21_telemetry_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T202112_blue_A0/20261101T202116_f5c1ad_blue_telemetry.jsonl
v21_planning_summary=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T202112_blue_A0/planning_runs.csv
Observer ready: waiting for first /mission_command; timing starts automatically.
{
  "run_id": "20261101T202116_1f9fd3",
  "target_color": "blue",
  "start_time": "2026-11-01T12:21:43.764+00:00",
  "end_time": "2026-11-01T12:24:05.726+00:00",
  "total_time": "141.962",
  "elapsed_time": "141.962",
  "bt_success": "true",
  "mission_success": "false",
  "end_status": "completed",
  "takeoff_status": "success",
  "cross_frame_status": "success",
  "detect_aruco_status": "success",
  "return_cross_frame_status": "success",
  "hit_balloon_status": "",
  "land_status": "success",
  "aruco_detect_time": "0.223",
  "balloon_search_time": "",
  "failure_stage": "hit_balloon",
  "failure_reason": "",
  "safety_boundary_triggered": "false",
  "boundary_first_time": "",
  "boundary_first_position": "",
  "boundary_violation_count": "0",
  "boundary_recovered": "",
  "notes": "mission_command received as text; SUCCESS received while stages were unobserved: hit_balloon; bt_planning_controls=[{\"goal\":\"{frame_center}\",\"offset_z\":\"1.000000\",\"kind\":\"frame_outbound\"},{\"goal\":\"{frame_center}\",\"offset_z\":\"\",\"kind\":\"frame_return\"},{\"goal\":\"5.3;1.0;0.7\",\"offset_z\":\"\",\"kind\":\"other\"}]; rosout_events_logged; setpoint_samples=7098; target_detection_messages=888"
}
csv=/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
raw_log=/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T202112_blue_A0/logs/20261101T202116_f5c1ad_blue.jsonl
```
