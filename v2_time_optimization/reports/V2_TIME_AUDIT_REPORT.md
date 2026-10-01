# V2 时间审计报告

## 审计范围

本报告只做静态源码审计和已有 JSONL 离线解析，没有启动仿真、没有发送 ROS 控制消息，也没有修改官方源码。审计对象是仓库中的原始快照 `official_baseline/catkin_ws`，并使用以下四局日志：

- `baseline_tools/results/logs/20260926T000255_054f21_red.jsonl`
- `baseline_tools/results/logs/20260927T215109_6714ec_purple.jsonl`（失败、越界后卡住）
- `baseline_tools/results/logs/20260927T220607_18c6b1_blue.jsonl`
- `baseline_tools/results/logs/20260928T002106_74b644_purple_v1.jsonl`

成功平均值使用 red、blue 和 purple V1 三局；失败的 purple 局单独列出，不混入成功平均值。

## 实际行为树链路

LLM 动态任务在 `src/mission_pkg/src/bt_ros.cpp:commandToXmlNode()` 中展开。正式自然语言链路实际生成的是：

```text
Takeoff
→ GoTo 观察点
→ Delay 2000 ms
→ TargetLocator 方框
→ PlanningControl 穿出方框
→ GoTo ArUco 观察点
→ Parallel(重复 GoTo + ArucoDetector)
→ GoTo 转向点并转向
→ GoTo planning_end_pos
→ PlanningControl 穿回方框
→ GoTo 机体系前进 0.5 m
→ GoTo 机体系前进 0.5 m 并转向出口
→ PlanningControl 气球接近点
→ GoTo 气球朝向
→ ForceSuccess(Timeout 50 s, Parallel(TargetTracker, VisualServo))
→ GoTo 起点
→ Land
```

源码依据：

- `bt_ros.cpp:244-266`：观察点、固定 Delay、TargetLocator、第一次 PlanningControl。
- `bt_ros.cpp:273-297`：ArUco、转向、返框、两个机体系 GoTo。
- `bt_ros.cpp:339-366`：气球区 PlanningControl、VisualServo、返航和降落。
- `mission_pkg/config/full_competition_purple.xml`：静态完整任务的对应节点顺序；正式 LLM 流程以动态 XML 为准。

行为树 tick 间隔为 10 ms（`bt_ros.cpp:508`）。GoTo 和 PlanningControl 都以 `checkArrival()` 的位置误差为主，带 yaw 的 GoTo 另外检查 yaw 误差；源码没有统一的速度稳定确认。

## 时间预算

单位：秒。动作时间来自日志中的明确开始和完成事件。

| 阶段 | 开始条件 | 结束条件 | red | blue | purple V1 | 成功平均 | 等待原因 / 固定等待 | 事件触发 | 优化潜力 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| Takeoff | `Takeoff start` | `OFFBOARD + armed + checkArrival` | 12.423 | 13.581 | 18.244 | 14.749 | 模式/解锁服务每 5 s 重试，随后位置到达；没有固定完成睡眠 | 已是状态触发 | 中，涉及飞控安全 |
| 观察点 GoTo | 观察点 `GoTo start` | `GoTo completed` | 1.608 | 2.002 | 1.881 | 1.830 | 位置误差阈值 0.15 m | 是 | 低 |
| 观察后 Delay | Delay 开始 | Delay 完成 | 2.002 | 2.003 | 2.002 | 2.002 | **固定 2000 ms**，来自 `cross_frame/observe_delay_ms` | 否 | **高，推荐优先替换** |
| TargetLocator | `Detecting target: square_frame` | `Target located ... SUCCESS` | 0.940 | 0.930 | 0.930 | 0.933 | 至少 10 个有效历史帧；等待感知事件 | 是 | 低到中，改滤波有感知风险 |
| 第一次穿框 PlanningControl | `Target acquired`（offset 1.0 m） | `Planning navigation completed` | 19.251 | 17.987 | 19.958 | 19.065 | Ego-Planner 速度/加速度约束和到达误差 | 是 | 高，但参数改动风险高 |
| ArUco 位置 GoTo | 到 ArUco 观察点 | 第一个 GoTo 完成 | 1.921 | 1.790 | 1.800 | 1.837 | 到达位置事件 | 是 | 低 |
| ArUco 检测 | `Detection ENABLED` | `ARUCO ID DETECTED` | 1.407 | 0.213 | 1.416 | 1.012 | 等检测结果，超时上限 20 s；成功时不是固定等待 | 是 | 低，不能删视觉反馈 |
| ArUco Parallel 内重复 GoTo | 第二个相同位置 GoTo | 完成 | 0.015 | 0.015 | 0.014 | 0.015 | 动态 XML 中重复同一目标，收益极小 | 是 | 很低 |
| 返框前转向 + 回规划终点 | 转向 GoTo | 回规划终点 GoTo 完成 | 9.465 | 13.581 | 12.896 | 11.981 | 位移和 yaw 逐步设定；紫色 V1 中该段受 yaw/位置误差影响 | 是 | 中 |
| 第二次穿框 PlanningControl | `Target acquired`（offset 0） | `Planning navigation completed` | 3.317 | 4.804 | 3.681 | 3.934 | Ego-Planner 短距离规划 | 是 | 中 |
| 返框后的两个机体系 GoTo | 第一个 body GoTo | 出口 yaw GoTo 完成 | 6.797 | 11.872 | 7.121 | 8.597 | 两个连续 0.5 m 动作；第二个还要从 π 转到 0，yaw_rate 默认 0.5 rad/s | 是 | 中，需先验证几何 |
| 气球区 PlanningControl | 气球 `Target acquired` | `Planning navigation completed` | 16.794 | 15.802 | 14.802 | 15.799 | 长距离 Ego-Planner 规划 | 是 | 高，但改 max_vel/max_acc 有安全风险 |
| 气球朝向 GoTo | 气球 GoTo start | `GoTo completed` | 3.207 | 3.924 | 5.996 | 4.376 | 位置已接近，主要剩 yaw 误差 | 是 | 中 |
| 气球搜索/逼近 | `Visual Servo Started` | 面积达到 8%，触发 `SPRINT` | 7.221 | 5.016 | 6.100 | 6.112 | TargetTracker 丢失时以 0.3 rad/s 搜索，重新检测后边飞边对准 | 是 | 中，需保留视觉闭环 |
| VisualServo Sprint | `-> SPRINT!` | `Sprint completed` | 1.204 | 1.204 | 1.205 | 1.204 | `sprint_time=1.2` 的明确固定阶段；本轮不修改 | 是（结束事件） | 暂不改 |
| 返航 GoTo | `GoTo (0,0,0.5) start` | `GoTo completed` | 6.572 | 8.573 | 9.688 | 8.278 | 位置和 yaw 到达；旧 purple 局在此阶段受 safety/hover lock 卡住 | 是 | 中，必须保留 V1 |
| Land | `AUTO.LAND` 请求 | `Landed and disarmed` | 5.368 | 5.883 | 5.926 | 5.726 | 等飞控落地并解锁；无固定完成睡眠 | 是 | 低到中 |

### 按竞赛阶段合并的成功平均值

| 竞赛阶段 | 包含动作 | 平均耗时 |
|---|---|---:|
| Takeoff | Takeoff | 14.749 s |
| First Cross Frame | 观察 GoTo + 2 s Delay + TargetLocator + 第一次 PlanningControl | **23.840 s** |
| ArUco | ArUco 位置 GoTo + 重复 GoTo + 检测 | 2.864 s（其中纯检测 1.012 s） |
| Return Cross Frame | 转向/回规划终点 + 第二次 PlanningControl + 两个机体系 GoTo | **24.512 s** |
| Balloon Positioning | 气球区 PlanningControl + 朝向 GoTo | **20.175 s** |
| Search Balloon | TargetTracker/VisualServo 启动到触发 Sprint | 6.112 s |
| VisualServo | Sprint | 1.204 s |
| Return Home | 起点 GoTo | 8.278 s |
| Land | AUTO.LAND 到解锁 | 5.726 s |
| 完整任务 | 上述阶段 | **107.466 s** |

三局成功的记录值为 red 99.554 s、blue 109.222 s、purple V1 113.702 s。差异主要来自起飞服务重试、Planner 路径执行、yaw 到达和环境状态，不应把单局最短时间当成稳定基线。

## 最大耗时模块排序

1. **Return Cross Frame：24.512 s**。两个世界系 GoTo、第二次 PlanningControl 和两个 body GoTo 串行执行；出口 yaw 约 7.531 s，明显受 0.5 rad/s yaw_rate 限制。
2. **First Cross Frame：23.840 s**。其中第一次 PlanningControl 平均 19.065 s；固定观察 Delay 另占 2.002 s。
3. **Balloon Positioning：20.175 s**。气球区 PlanningControl 平均 15.799 s，之后 GoTo 主要做朝向，平均 4.376 s。
4. **Takeoff：14.749 s**。部分局出现 5 s 间隔的 OFFBOARD/ARM 请求重试。
5. **Return Home：8.278 s**。这是旧 purple 失败局的卡死位置，任何优化必须保留 V1 Safety Recovery 的最终控制权。
6. **Search Balloon：6.112 s**。由目标丢失搜索和视觉逼近组成，没有固定睡眠。
7. **Land：5.726 s**。

## 固定等待与可并行性判断

- 明确固定等待只有动态 `cross_frame` 的 2000 ms Delay；它位于 GoTo 完成之后，最适合用“位置误差 + 速度 + 连续稳定时间”事件替代。
- ArUco 与同位置 GoTo 在 Parallel 中并行，但动态 XML 仍保留一个几乎立即完成的重复 GoTo，收益不足以单独作为第一 patch。
- TargetTracker 与 VisualServo 已在 Parallel 中并行；不能为了提速移除 TargetTracker 或视觉反馈。
- PlanningControl 的目标发布和 GoTo/PlanningControl 顺序由行为树定义。把多个动作合并会改变方框穿越和安全边界时序，需单独验证，不应在没有回归测试时直接改。
- `ForceSuccess` 只包住气球阶段，不能把 BT `SUCCESS` 当成全部比赛阶段成功；时间审计仍以每个明确完成事件为准。

## 审计结论

第一批 V2 应只处理观察点后的固定 Delay，并保留一个不超过当前 2 s 的超时保护。Ego-Planner 参数、yaw 速率、body GoTo 合并和 VisualServo 参数都可能节省更多时间，但会直接影响飞行轨迹或安全边界，放到后续实验批次。V1 Safety Recovery 在任何 V2 patch 中必须保持不变。
