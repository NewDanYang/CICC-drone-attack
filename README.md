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

详细修改内容请参阅：

- `v1_safety_recovery/patches/safety_recovery_v1.0.diff`
- 对应的验证报告

## V1 参数

```yaml
safety/recovery_margin: 0.20
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

但该次测试**尚未独立验证 Recovery 恢复分支本身是否能够正常工作**。

## 恢复原版

V1 修改前的原始源码校验信息保存在：

- `v1_safety_recovery/SHA256SUMS.original.txt`
- 对应的备份记录中

本地恢复辅助脚本为：

```text
v1_safety_recovery/restore_safety_recovery_v1.0.ps1
```
