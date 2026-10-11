# PX4/RflySim 气球任务中期报告

日期：2026-10-11
工作空间：`/home/ubuntu/catkin_ws`

## 一、阶段目标

本阶段围绕三项能力进行验证和修复：

1. ArUco 识别与任务航线执行；
2. 规划器避障、返航和降落停稳；
3. 红、紫、蓝气球的视觉跟踪与击球。

所有飞行试验均在结束后确认飞控 `connected=True`、`armed=False`，并保留日志、rosbag、参数和现场观察记录。

## 二、已完成的功能

### 1. ArUco 检测

ArUco 节点已完成离线部署和回调验证。连续五轮回调测试均检测到 ID 43，并在检测成功后自动取消图像订阅以节省 CPU。

实际飞行任务中多次稳定检测到 ID 35，任务日志包含：

```text
ARUCO ID DETECTED: 35
```

离线部署和验证证据位于历史 `aruco_v3_offline_*` 目录及对应飞行记录中。

### 2. 规划导航和返航视野

已接入 EGO Planner 的点云输入和轨迹输出，并增加规划门控：

- 等待规划目标订阅者和基线轨迹；
- 等待新鲜轨迹后才执行目标移动；
- 轨迹停滞时保持位置；
- 返航前先转向返航方向；
- 等待新鲜点云后再发送返航目标。

返航视野修复后，连续两轮观察结果均为先掉头、绕墙、正常落地。典型证据：

```text
/home/ubuntu/landing_retest_20261011T012235/return_view_trial_20261011T022151
/home/ubuntu/landing_retest_20261011T012235/return_view_trial_20261011T023003
```

飞行地图检查显示规划中心线未穿过占用格；实际轨迹存在少量接近膨胀障碍格的候选点，因此只能说明本轮未观察到碰撞，不能证明所有姿态和传感器覆盖条件下都绝对安全。

### 3. 降落停稳

已加入降落前停稳门控：

```text
arrival_tolerance=0.10 m
settle_time=1.0 s
settle_speed_threshold=0.15 m/s
return_pos=0.0;0.0;0.5
```

复测中降落前速度保持在阈值内，落地后漂移约 0.004–0.038 m，最终均为：

```text
armed: False
mode: AUTO.LAND
```

### 4. 视觉冲刺对齐

此前红球试验中，目标面积达到阈值但横向偏差达到约 234 像素，仍然触发冲刺，导致未命中。已部署 V4 对齐门控：

- 面积达到阈值且目标居中，才允许进入 `SPRINTING`；
- 面积达标但偏心时继续对准；
- 保留原速度参数和安全边界。

部署证据：

```text
/home/ubuntu/visual_sprint_alignment_v4_backup_20261011T025959
```

随后发现偏航控制符号与仿真相机方向不一致，已部署 yaw direction v1 修复：

```text
/home/ubuntu/visual_yaw_direction_v1_backup_20261011T031447
```

### 5. 目标丢失搜索限时

紫球任务曾出现长时间原地摇摆。已部署 bounded visual search v1/v3：

- 目标丢失后搜索时间限制为 8 秒；
- 超时后悬停，不再无限旋转；
- 采用累计计时，零星重新检测不会重置总搜索窗口。

最终部署证据：

```text
/home/ubuntu/bounded_visual_search_v3_backup_20261011T040040
```

## 三、击球试验结果

### 红球

首次红球回归未破，原因是面积达标时目标严重偏心。随后部署居中冲刺逻辑，重新试验时用户确认：

```text
红球已破
```

证据目录：

```text
/home/ubuntu/hit_balloon_trials/red_regression_20261011T030125
```

该轮日志出现目标丢失后的 `SUCCESS`，因此击破结论依赖用户现场观察，不能只依据任务状态。

### 紫球

紫球多轮试验均未形成可靠击破：

```text
/home/ubuntu/hit_balloon_trials/purple_regression_20261011T030532
/home/ubuntu/hit_balloon_trials/purple_regression_20261011T031644
/home/ubuntu/hit_balloon_trials/purple_regression_20261011T034032
/home/ubuntu/hit_balloon_trials/purple_regression_20261011T040323
```

关键现象：

- 目标类别筛选正确，日志明确为 `purple_balloon`；
- 曾出现目标从画面中心漂移到左侧，误差约 `-218 px`；
- 偏航角速度达到 `+0.500` 饱和；
- 居中门控阻止了冲刺；
- 后续限时搜索减少了持续摇摆，但仍未完成紫球击球；
- 最新一轮未持续摇摆，紫球未破，蓝球仅经过且未破；
- 最新一轮触发过 `SafetyRecovery`，位置接近边界，随后安全返航降落。

### 蓝球

尚未完成独立、可靠的蓝球击球回归。此前紫球试验中出现过蓝球误碰/误击的现场现象，但未形成蓝球目标任务的有效成功证据。

## 四、已确认的问题

### 1. `SUCCESS` 语义过宽

击球行为树仍包含：

```xml
<ForceSuccess>
```

视觉伺服在目标丢失、达到面积但未冲刺等情况下也可能返回 `SUCCESS`。因此：

```text
Mission result: SUCCESS
```

不等于气球已经击破。

### 2. 紫球对准方向和搜索仍不稳定

虽然修复了偏航符号并限制了搜索时长，但紫球任务仍可能在进入冲刺前丢失目标。需要进一步验证相机坐标、偏航方向、目标平滑和规划到打击区的最终姿态。

### 3. 边界恢复曾被触发

最新紫球试验出现：

```text
[SafetyRecovery] ENTER DRONE OUT OF BOUNDARY
```

恢复动作最终完成，但说明紫球路线或目标丢失后的控制仍可能把无人机带到边界附近。

## 五、阶段性结论

当前阶段可以确认：

- ArUco 检测链路可用；
- 规划去程和返航在多轮试验中未观察到穿墙，返航前转向有效；
- 降落停稳和解除武装稳定；
- 红球至少有一轮得到用户现场确认击破；
- 紫球尚未可靠击破；
- 任务状态 `SUCCESS` 不能作为击球成功判据；
- 限时搜索已减少无限摇摆，但尚未解决紫球丢失和边界接近问题。

## 六、下一阶段建议

暂停继续扩大颜色回归轮数，优先完成以下修复：

1. 去除或改造击球阶段的 `ForceSuccess` 语义，使未冲刺或搜索超时明确记录为失败，同时保留安全返航和降落；
2. 为击球成功增加明确证据，例如冲刺完成且目标在冲刺前居中，或冲刺后目标连续消失并满足最小时间条件；
3. 复核紫球路线的打击区位置、相机朝向和偏航符号；
4. 在不越过安全边界的前提下，降低紫球试验的前进速度或缩短搜索动作；
5. 修复 `ROS_INFO` 冲刺日志的格式警告，避免误导性日志；
6. 完成紫球稳定成功后，再进行蓝球和至少五轮覆盖三种颜色的回归。

## 七、重要证据目录

```text
/home/ubuntu/hit_balloon_trials/red_regression_20261011T030125
/home/ubuntu/hit_balloon_trials/purple_regression_20261011T040323
/home/ubuntu/landing_retest_20261011T012235/return_view_trial_20261011T022151
/home/ubuntu/landing_retest_20261011T012235/return_view_trial_20261011T023003
/home/ubuntu/visual_sprint_alignment_v4_backup_20261011T025959
/home/ubuntu/visual_yaw_direction_v1_backup_20261011T031447
/home/ubuntu/bounded_visual_search_v3_backup_20261011T040040
```

