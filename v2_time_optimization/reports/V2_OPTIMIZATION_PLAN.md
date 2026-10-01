# V2 优化方案设计

## 约束

- 保持九格自然语言 → `/mission_command` → 动态 Behavior Tree → 感知/规划 → MAVROS 的接口和任务顺序。
- 不使用固定坐标替代视觉反馈，不新增复合任务指令。
- 不改变 V1 Safety Boundary Recovery 的状态机、最终 publish 层控制权和参数。
- 不修改 VisualServo 的 `sprint_velocity`、`sprint_time`，不修改 Ego-Planner 参数作为第一 patch。
- 所有源码改动都要在 `v2_time_optimization/backups` 中备份并记录 SHA256、diff 和恢复方法；本报告阶段尚未修改源码。

## 候选优化

| 修改 | 证据 / 预计收益 | 风险 | 是否推荐进入第一批 |
|---|---|---|---|
| 用稳定状态替换观察点后固定 2000 ms Delay | 源码 `bt_ros.cpp:244-266` 明确生成 2 s Delay；三局均完整消耗 2.002 s。预计节省 0 至 1.5 s，取决于位置和速度收敛 | 新增状态节点或等待逻辑若判定过早，会让 TargetLocator 在机体未稳定时开始 | **推荐** |
| 增加 `position_threshold`、`velocity_threshold`、`stable_confirm_time`、`settle_timeout` | 让等待有可解释的事件条件；超时回退到保守上限，不改变任务接口 | 需要 odom 速度质量和参数回归 | **推荐，和上项一起做** |
| 删除 ArUco Parallel 中重复同位置 GoTo | 日志平均仅 0.015 s；收益很小，且需改变 Parallel 成功条件 | 可能改变 BT 并行完成语义 | 暂不推荐 |
| 合并两个 body GoTo | 返框后的两个 body GoTo 平均合计 8.597 s；可减少一次 waypoint 切换，理论收益约 0.8 至 1.4 s | 第二段目标是基于第一次动作后的机体姿态计算，直接合并可能改变穿框出口轨迹 | 后续实验 |
| 在 PlanningControl 中同时管理目标 yaw | 气球朝向 GoTo 平均 4.376 s，返框出口 yaw 也占 7.531 s | 需要确认 `/planning/pos_cmd` yaw 语义和安全控制优先级，改动影响大 | 后续实验 |
| 提高 Ego-Planner `max_vel/max_acc` | 两段长规划合计约 34.9 s，是理论上最大收益点 | 直接改变飞行安全裕量，可能重新触发 V1 boundary recovery 或穿框失败 | 不进入第一批 |
| 调整 `planning_horizon`、`time_forward`、障碍膨胀 | 可能减少重规划和保守绕行 | 影响碰撞约束，日志不能证明参数是瓶颈 | 不进入第一批 |
| 调整 VisualServo 搜索或 Sprint | 搜索平均 6.112 s，Sprint 固定 1.204 s | 会改变视觉闭环和打击安全；用户已要求暂不动 Sprint 参数 | 不进入第一批 |
| 缩短 Takeoff/Land 的服务重试间隔 | 起飞平均 14.749 s，部分局确有 5 s 重试 | 影响 PX4 模式、解锁和落地安全 | 不进入第一批 |

## 推荐的 V2.0 Patch 1

只替换 `cross_frame` 观察点后的固定 Delay：

```text
GoTo 观察点
→ WaitForStablePosition
   position_error <= optimization/position_threshold
   speed <= optimization/velocity_threshold
   连续满足 optimization/stable_confirm_time
   最长等待 optimization/settle_timeout
→ TargetLocator
```

建议初始参数（待确认后写入 `mission_pkg/launch/llm_mission.launch`）：

```text
optimization/position_threshold = 0.15 m
optimization/velocity_threshold = 0.08 m/s
optimization/stable_confirm_time = 0.50 s
optimization/settle_timeout = 2.00 s
```

这些默认值保持当前 2 s 的安全上限。若速度在位置到达后已经稳定，等待会在 0.5 s 连续确认后结束；若不稳定，则不早于当前上限继续任务。该节点只等待状态，不向飞控发布额外控制，最终控制仍由行为树动作和 V1 Safety Recovery 管理。

## 实施后验证门槛

收到确认后，实施步骤应为：

1. 备份涉及的 `bt_ros`、新增等待节点、头文件、CMake/插件注册和 launch 文件，并记录 SHA256。
2. 生成单独 patch 和恢复脚本；不触碰 `official_baseline` 原始快照。
3. `catkin_make --pkg mission_pkg` 编译。
4. 先做 XML/参数/单元逻辑检查，再分别跑 red、purple、blue 单局，禁止自动连续运行。
5. 每局记录总耗时、各 PlanningControl/GoTo 时间、mission success、BT success、Safety Recovery 触发与完成情况。
6. 只有三色成功率不下降、没有新增 boundary/stuck、并且观察等待平均时间下降时，才保留 patch。

## 当前状态

本报告阶段只完成离线时间审计和方案设计。没有创建备份、没有修改源码、没有编译、没有启动仿真。等待人工确认后再建立 `v2_time_optimization/backups/patches/experiments` 并实施第一 patch。
