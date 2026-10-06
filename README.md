# CICC 无人机搜索打击

本仓库将 TCEI 无人机搜索打击项目按三个独立层级进行保存。

## 目录结构

### `official_baseline/`

保存用于 baseline 测试的原始官方 ROS1 / PX4 / MAVROS / RflySim 工作空间快照。其中包含原始 `src/` 源码树以及官方启动脚本：

- `official_baseline/catkin_ws/src/`
- `official_baseline/catkin_ws/sim_env_start.sh`
- `official_baseline/catkin_ws/kill_ros_pid.sh`

该副本保持不变，作为后续开发和实验的官方基准参考。

### `baseline_tools/`

独立的、仅用于观察和记录的 baseline 测试工具：

- `run_baseline.py`
- `results/baseline_runs.csv`
- `results/logs/`：保存选取的红球、紫球、蓝球 baseline JSONL 日志，以及 V1 紫球正式测试日志
- `results/formal_purple_v1_report.md`
- `run_formal_trial.sh`：单局、非交互、带 readiness/cleanup 的正式任务编排
- `start_sim_environment.sh`：服务器重启后只执行一次的 SITL + sim_env 启动器

该观察工具仅监听 ROS 中的相关证据，不会发布任何飞行控制指令。自然语言任务输入仍然完全通过官方 `mission_once.py` 链路执行。

### `v1_safety_recovery/`

V1 Safety Boundary Recovery（安全边界恢复）覆盖层。

该覆盖层仅修改以下官方源码路径：

- `src/mission_pkg/src/mavros_cnt.cpp`
- `src/mission_pkg/include/mavros_cnt.h`
- `src/mission_pkg/launch/llm_mission.launch`

该版本新增了：

- `NORMAL` / `RECOVERING` 状态
- 向安全区域内部移动的恢复目标点
- 内部安全边界持续确认机制

在恢复过程中，共享的 Behavior Tree 控制命令仍可正常更新；完成安全确认后，系统会恢复执行最新的行为树控制命令。

详细修改内容和使用步骤请参阅：

- `v1_safety_recovery/patches/safety_recovery_v1.0.diff`
- 对应的验证报告
- `v1_safety_recovery/README.md`

## V1 参数

```yaml
safety/recovery_target_margin: 0.30
safety/release_margin: 0.15
safety/recovery_confirm_time: 0.50
```

原始安全边界参数保持不变。

## 已记录的 V1 紫球测试结果

在重新编译 `mission_pkg` 后进行的第一次正式紫球测试已完整成功：

- `bt_success=true`
- `mission_success=true`
- 总耗时：`113.702 s`
- 未触发安全边界

该次运行并未进入 `RECOVERING` 状态，因此它只能确认：

- V1 修改未对正常任务流程造成回归
- 完整任务可以正常完成

该次测试**未能验证 Recovery 恢复分支本身**。

## Recovery 恢复分支已验证（2026-10-06）

后续排查发现：**该修复当时并未部署到运行版本**。服务器实际运行的 `mavros_cnt.cpp`
是滞回修复之前的旧版（只读 `safety/recovery_margin`），因此目标点被 clamp 到
`y_max - 0.20 = 2.80`，正好压在内边界上，恢复确认永远无法锁存，任务必然卡到
300 s 超时。这一问题在 `20261001T161850` 与 `20261005T131925` 两局中稳定复现，
每局损失气球 25 分 + 降落 5 分。

2026-10-06 已将该修复正式部署（代码 + launch 参数 + 重新编译），并**主动构造越界
完成验证**：

- 单局连续 3 次越界，恢复全部完成（4.920 / 2.520 / 2.000 s）
- 确认重置 0 次，`boundary_recovered=true`
- `mission_success=true`，六阶段全部通过

详细过程、证据文件与工具见 **`v3_stability/README.md`**。

### `v3_stability/`

2026-10-06 一轮工作的部署产物与验证记录：

- `safety_recovery/`：已部署的安全参数解耦版 `llm_mission.launch`
- `aruco/`：ArUco 识别节点健壮性修复（含修复前原版，便于回滚）
- `tools/`：字节级 launch 补丁、越界测试构造、恢复判读、ArUco 离线 A/B、服务器控制
- `reports/`：越界验证的原始日志证据

该轮另修复了 ArUco 节点中"调试绘图异常会吞掉识别结果"的结构性缺陷，
并打通了无需网页桌面的无头启动方式。

## 恢复原版

V1 修改前的原始源码校验信息保存在：

- `v1_safety_recovery/SHA256SUMS.original.txt`
- 对应的备份记录中

本地恢复辅助脚本为：

```text
v1_safety_recovery/restore_safety_recovery_v1.0.ps1
```
