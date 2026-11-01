# FM9G VisualServo 容差验证（5.6b）

日期：2026-11-01（Asia/Shanghai）

## 结论

本任务按交接要求完成了两次、且仅两次单局尝试：

1. 红色 `deadzone_yaw=20.0`、`deadzone_vz=20.0`；
2. 回滚冻结版后，紫色 `deadzone_yaw=30.0`、`deadzone_vz=30.0`。

两局都没有进入 VisualServo：原始 rosout 中 `Visual Servo Started=0`、`Aligned!=0`、`SPRINT_START=0`。两局均在前置导航到 `(4.30, 1.00, 0.70)` 时卡住，5 分钟超时。因此不能把这两局解释成“20 px 不收敛”或“30 px 不收敛”；容差假设在本次实飞中**没有获得有效观测**。任务报告不选择三项容差结论中的任何一项，原因是 ALIGN 根本没有执行。

红紫近距离丢失规则的结论仍为：**回测发现误触发风险，未部署**。最终服务器已恢复冻结版本，阶段 D 继续暂停，等待人类决定是否先修复前置 `(4.3, 1.0, 0.7)` 航点停滞。

## 版本、备份和编译证据

服务器启动前没有正式试验锁；仅发现一个无 PX4 进程对应的 `/tmp/px4_lock-1`，确认无 PX4 进程后清除。冻结版本为：

- `visual_servo.cpp`: `a63b57fa127a23cd8bb8e647f078ff21`
- `visual_servo.h`: `d3324b0458b2160102f9bbf44546d035`
- `visual_servo.so`: `6ddfa7c180ae18f5097efd95d369b97f`

两次修改均由 MD5 守卫脚本执行，并分别备份到服务器：

- `/home/ubuntu/visualservo_tolerance_backup_20261101_20px/`
- `/home/ubuntu/visualservo_tolerance_backup_20261101_30px/`

|版本|源码 MD5|插件 MD5|编译结果|
|---|---|---|---|
|冻结|`a63b57fa...`|`6ddfa7c1...`|已核对|
|20/20|`b8f4201d684e4386b9e003500902bd47`|`bc9b1f5327472840f663da536acf684b`|`catkin_make --pkg mission_pkg` 成功|
|30/30|`6fbb6a2c288165f276c0302fe21fcf5f`|`51c3f7a470b58d393bb2671c4f28ad90`|`catkin_make --pkg mission_pkg` 成功|
|最终恢复|`a63b57fa...`|`6ddfa7c1...`|恢复后重新编译并核对|

两个候选补丁的静态差分只改变两个 InputPort 默认值：

- [`deadzone_20_dryrun.diff`](evidence/deadzone_20_dryrun.diff)
- [`deadzone_30_dryrun.diff`](evidence/deadzone_30_dryrun.diff)

最终状态见 [`final_status.txt`](evidence/final_status.txt)，恢复编译日志见 [`final_rollback_compile.log`](evidence/final_rollback_compile.log)。

## 第一次尝试：20/20 红色

试验目录：服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T153622_red_A0/`。

- 任务时间：`2026-11-01T07:36:43.119Z` 至 `07:41:43.254Z`，`300.135 s`。
- `takeoff`、穿框、ArUco、回穿在观测器中被记录为成功；进入气球阶段前停滞。
- `checkArrival` 连续检查目标 `(4.30, 1.00, 0.70)`，末次观测无人机位置约 `(2.89, -1.09, 0.89)`，距离 `2.527 m`，容差 `0.15 m`。
- `Visual Servo Started=0`、`Aligned!=0`、`SPRINT_START=0`。
- 观测器结果是 `mission_timeout: no /mission_result received`，不能作为 VisualServo 失败证据。

原始证据：

- [`trial_rosout.jsonl.gz`](evidence/attempt20/trial_rosout.jsonl.gz)
- [`telemetry.jsonl.gz`](evidence/attempt20/telemetry.jsonl.gz)
- [`mission_once.out`](evidence/attempt20/mission_once.out)
- [`observer.out`](evidence/attempt20/observer.out)
- [`audit.jsonl`](evidence/attempt20/audit.jsonl)
- [`compile.log`](evidence/attempt20/compile.log)
- [`rollback_compile.log`](evidence/attempt20/rollback_compile.log)

审计只包含 `processor_input`、`presence_warmup`、`ready`、`camera_contract`、`closed`，没有视觉伺服窗口；这与原始 rosout 一致。

## 第二次尝试：30/30 紫色

第一次结束后先回滚到冻结源码和二进制，再编译确认，然后才部署 30/30。试验目录：服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T154543_purple_A0/`。

- 任务时间：`2026-11-01T07:46:12.209Z` 至 `07:51:12.322Z`，`300.113 s`。
- 同样停在目标 `(4.30, 1.00, 0.70)`，末次 `checkArrival` 位置约 `(2.93, -1.10, 0.87)`，距离 `2.512 m`，容差 `0.15 m`。
- `Visual Servo Started=0`、`Aligned!=0`、`SPRINT_START=0`。
- 观测器将该局归类为 `takeoff` 停滞，但原始 `checkArrival` 日志显示是前置目标未到达；没有证据表明容差参数被执行。

原始证据：

- [`trial_rosout.jsonl.gz`](evidence/attempt30/trial_rosout.jsonl.gz)
- [`telemetry.jsonl.gz`](evidence/attempt30/telemetry.jsonl.gz)
- [`mission_once.out`](evidence/attempt30/mission_once.out)
- [`observer.out`](evidence/attempt30/observer.out)
- [`audit.jsonl`](evidence/attempt30/audit.jsonl)
- [`compile.log`](evidence/attempt30/compile.log)

两局的机器可读摘要见 [`attempt_summary.json`](evidence/attempt_summary.json)。

## 红紫近距离丢失规则回测

离线回测没有改代码，使用 3.3 封存对照及 1.6 历史验收证据。规则条件为：

```text
max_area_ratio >= 0.30
last_ratio >= 0.50 * 0.08 = 0.04
lost_seconds <= data_timeout + 0.25 = 1.25 s
```

关键风险窗口仍然成立：

- `hit_balloon_part1_1.3 / batch1 / r3_purple_a1`：丢失前面积 `35.5%`，无 `SPRINT_START`；Actor 快照约 73 秒后才显示目标消失。
- 1.6 `B_v3/r1_purple_a1`：`61.9%`，无冲刺，Actor 删除延迟约 `58.7 s`。
- 1.6 `purple_forward/r1_purple_a1`：`65.8%`，无冲刺，延迟约 `87.9 s`。
- 1.6 `purple_forward/r2_purple_a1`：`54.9%`，无冲刺，延迟约 `41.0 s`。

这些窗口不能证明目标在第一次视觉丢失时已被击破，因此扩展红紫规则可能提前返回成功。逐局结果见：

- [`rule_backtest_summary.md`](evidence/rule_backtest_summary.md)
- [`rule_backtest_summary.csv`](evidence/rule_backtest_summary.csv)
- [`historical_extra_qualifying_windows.csv`](evidence/historical_extra_qualifying_windows.csv)

规则结论为**未部署**，服务器最终源码中没有红紫扩展。

## 收尾和下一步边界

两次尝试结束后，服务器已停止仿真节点，清理正式试验锁、仿真锁和 PX4 临时锁；最终源码和插件 MD5 已恢复到冻结值。没有进行第三次碰运气测试，也没有开始阶段 D。

如果继续研究，下一步应先单独定位 `(4.3, 1.0, 0.7)` 前置航点停滞，再重新安排容差台架；不能使用本次两局作为 20/30 像素收敛率证据。
