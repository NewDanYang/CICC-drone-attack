# Offline ArUco observation-window comparison

窗口：每局第一次 `PlanningControl completed`（`first_cross_frame_planning.end_time`）到 `ArucoDetectNode Detection ENABLED`，并分析 ENABLED 后 3.0 s。

说明：规划实际使用 `/rflysim/uav1/local/odom` 的位置；该 topic 在日志中速度恒为 0。`/mavros/local_position/odom` 提供非零速度，但其位置坐标与 RflySim 位置不是同一表示，因此位置和速度分开报告。

| 局次 | PlanningControl→ENABLED | ENABLED 时 GoTo hover xyz/yaw | hover 到 (4.5,0.5,1.2) 误差 | 最后采样 checkArrival | 3s RflySim xyz 首→末 | 3s MAVROS speed 均值/峰值 | setpoint mask/frame；raw xyz 首→末 | reject 20s（消息/候选） | 结果 |
|---|---:|---|---:|---|---|---:|---|---:|---|
| A0 | 1.999s | (4.54, 0.45, 1.13) / yaw -0.03 | 0.095m | (4.47,-0.22,1.11) / d=0.723 | (4.54, 0.49, 1.13) → (4.51, 0.07, 1.74) | 0.329/0.787 | [3064]/[1]; (-0.45, 4.54, 1.13) → (-0.50, 4.50, 1.80) | 0/0 | detected |
| A1 | 2.200s | (4.48, 0.36, 1.23) / yaw -0.02 | 0.145m | (4.45,0.00,1.23) / d=0.501 | (4.48, 0.37, 1.23) → (4.49, -0.22, 1.75) | 0.339/0.762 | [3064]/[1]; (-0.36, 4.48, 1.23) → (-0.50, 4.50, 1.80) | 1/4 | detected |
| A2 #1 | 1.887s | (4.55, 0.42, 1.25) / yaw -0.05 | 0.107m | (4.43,-0.19,1.21) / d=0.695 | (4.56, 0.50, 1.25) → (4.56, 0.32, 1.31) | 0.246/0.785 | [3064]/[1]; (-0.42, 4.55, 1.25) → (-0.42, 4.55, 1.25) | 0/0 | timeout |
| A2 retry | 1.917s | (4.60, 0.47, 1.15) / yaw -0.02 | 0.116m | (4.18,-0.96,1.02) / d=1.505 | (4.61, 0.53, 1.15) → (4.64, 0.37, 1.12) | 0.241/0.737 | [3064]/[1]; (-0.47, 4.60, 1.15) → (-0.47, 4.60, 1.15) | 10/39 | timeout |
| A1 retest | 1.808s | (4.47, 0.39, 1.14) / yaw -0.06 | 0.129m | (4.40,0.03,1.11) / d=0.486 | (4.49, 0.48, 1.14) → (4.78, 1.89, 1.85) | 0.567/0.989 | [3064]/[1]; (-0.39, 4.47, 1.14) → (-0.50, 4.50, 1.80) | 1/5 | detected |

## 字段可用性

- 日志没有逐帧 PX4 `/mavros/state`，因此无法离线给出窗口内 mode/armed 时间序列；只能看到 `Requesting mode OFFBOARD` 和成功局的 `Requesting mode AUTO.LAND`。
- Odom observer 没有保存姿态四元数；实际 roll/pitch/yaw 不可恢复。可用的 yaw 只有 GoTo hover 日志、`/planning/pos_cmd` yaw 和 `/mavros/setpoint_raw/local` yaw。
- `type_mask=3064`、`coordinate_frame=1` 在所有窗口一致：位置和 yaw 字段有效，速度、加速度/力、yaw_rate 被忽略；setpoint 速度字段均为 0。
- `checkArrival` 不是每个循环逐帧记录；表中是完成前最后一条采样，不能冒充真正的完成瞬间。

## 为什么 A2 #1 位置/yaw 接近成功样本仍失败

1. 几何条件没有显示出失败：A2 #1 hover=(4.55,0.42,1.25)，到 GoTo 目标约 0.096 m；A0/A1/A1 retest 分别约 0.132/0.142/0.136 m，A2 retry 约 0.117 m，均在 0.15 m 量级，hover yaw 也都在约 -0.06 到 -0.02 rad。
2. A2 #1 的关键证据不是“连续 rejected”：在 ENABLED 后完整 20 s，日志中 **没有任何** `Searching... no marker found (rejected: N)`，也没有 detected 事件。也就是说离线日志只能证明 ArUco 图像回调/候选处理没有留下候选结果，不能证明它对每帧都拒绝了 marker。
3. A2 retry 则确实进入了图像检测回调：20 s 内有 10 条 throttled reject 日志，候选数合计 39，但仍未识别。成功局在 0.21–1.33 s 内识别，后续 setpoint 才切换到上升 GoTo；失败局 setpoint 在 3 s 窗口保持悬停位置，说明失败发生在识别输入阶段而非后续运动。
4. 因此“最终 hover xyz/yaw 几乎一致”不能保证识别结果一致。更符合日志证据的解释是 ArUco 图像输入/回调时序或当前帧内容不同：A2 #1 是无候选处理迹象，A2 retry 是候选持续被拒绝。现有 observer 没有记录 `/rflysim/sensor2/img_rgb` 的帧率、header 时间戳、图像哈希或原始图像，无法进一步把两者区分为“无帧”“空帧”还是“图像质量不足”。

## 结论

不能依据这五局离线日志把 A2 失败归因于位置、速度、yaw 或 setpoint 类型；这些控制量在 ENABLED 时高度相似。下一步若要定因，应增加只读观测：`/rflysim/sensor2/img_rgb` 到达计数/时间戳、ArUco callback 处理计数、`/mavros/state` 采样，以及图像处理前后的候选数。
