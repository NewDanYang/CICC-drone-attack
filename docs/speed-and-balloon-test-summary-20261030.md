# 速度参数与三色气球测试总结（2026-10-30）

本文件记录服务器现场审计、三色气球正式试验，以及自动记录与现场观察之间的差异。它是测试证据汇总，不代表服务器源码已经与仓库主分支自动同步。

## 1. 审计基准与部署边界

- 仓库：`NewDanYang/CICC-drone-attack`
- 审计基准提交：`6499977d076a940b07e4466543f2ed1cbd306a3e`
- 服务器测试工作区：`/home/ubuntu/cicc_v1_stage_20261005/`
- 正式测试脚本：`baseline_tools/run_formal_trial.sh`
- 服务器只读审计报告：`baseline_tools/cicc-speed-audit-ou1hqt4f.tar.gz`
- 审计报告 SHA256：`f31ebc3e0f6bc097b8a409410ae001e96572ca5756db8889c4a20e9b97a08380`

本次审计没有重新编译、部署源码、重启 ROS 或替换运行中的二进制。因而以下参数是现场运行态读数，不能推导出服务器已经部署了某个 Git 提交。

## 2. 速度数值分类

### 2.1 Ego-Planner 规划速度上限

| ROS 参数 | 现场值 | 作用 |
| --- | ---: | --- |
| `/ego_planner_node/manager/max_vel` | `0.30 m/s` | 管理层速度上限 |
| `/ego_planner_node/optimization/max_vel` | `0.30 m/s` | 优化层速度上限 |
| `/ego_planner_node/bspline/limit_vel` | `0.30 m/s` | B-spline 轨迹限速 |

正式脚本的 V2.1 遥测配置也使用 `V21_MAX_VEL=0.30`。这些是规划或轨迹约束，不等于每一时刻无人机的实际速度。

### 2.2 VisualServo 速度参数

| ROS 参数 | 现场值 | 作用 |
| --- | ---: | --- |
| `/visual_servo/forward_velocity` | `1.00 m/s` | 目标跟踪接近速度 |
| `/visual_servo/sprint_velocity` | `1.50 m/s` | 满足面积和居中条件后的冲刺速度 |
| `/visual_servo/sprint_time` | `1.20 s` | 冲刺持续时间 |

代码和运行日志中的 `forward_vel=1.00`、`sprint_vel=1.50` 是控制目标配置；不能当作实际飞行速度。正式试验启用了独立遥测，实际速度应从每轮的 `*_telemetry.jsonl` 中读取 `/rflysim/uav1/local/odom`、`/planning/pos_cmd` 和 `/mavros/setpoint_raw/local` 的 `speed` 字段。

### 2.3 已知代码差异

服务器仍保留 FM9G 目标选择、非目标保护、稳定等待、规划导航/返航等增强逻辑；`visual_servo.cpp` 的偏航控制符号也与 official baseline 不同。服务器 `bt_ros.cpp` 现场审计确认没有蓝球专用 `1.0` 特判，而是统一读取 `sprint_velocity`。因此不能把本次运行称为“整套代码与官方基线完全一致”。

## 3. 场景与测试方法

- 测试前通过 UE 对象清单确认 `reported_count: 3`。
- 为避免重复创建演员，只保留一个 `AgentContestMap.py` 进程；重复启动该脚本会造成气球数量增加或位置争抢。
- 每轮使用 `run_formal_trial.sh <color>`，脚本自动记录 observer、任务标准输出、原始 JSONL 日志和 V2.1 遥测。
- 现场观察与自动判据分别记录，不能用单一 `mission_success` 字段替代气球实际破裂证据。

## 4. 三色测试结果

### 4.1 紫球

试验目录：

`/home/ubuntu/cicc_v1_stage_20261005/baseline_tools/results/formal_trials/20261030T005356_purple_V1/`

自动摘要：

- 总耗时：`141.199 s`
- 行为树结果：`SUCCESS`
- 起飞、出框、二维码识别、返框、降落：有成功记录
- `hit_balloon_status`：未确认
- 现场观察：**紫球未命中**

视觉伺服日志显示：

- 目标最初只占约 `1.0%`，最大面积约 `1.1%`
- 目标横向误差由约 `-201` 扩大到约 `-288` 像素
- 未达到 `8%` 冲刺面积门槛
- 约 8 秒后：`Target search timeout ... before confirmed sprint; FAILURE`
- 整轮仍返回 `SUCCESS`，原因是打击节点外层使用了 `ForceSuccess`

结论：紫球为**未命中**，且未进入冲刺。

### 4.2 蓝球

试验目录：

`/home/ubuntu/cicc_v1_stage_20261005/baseline_tools/results/formal_trials/20261030T010721_blue_V1/`

自动摘要：

- 总耗时：`141.652 s`
- 行为树结果：`SUCCESS`
- 起飞、出框、二维码识别、返框、降落：有成功记录
- `hit_balloon_status`：未确认
- 现场观察：**蓝球命中**

视觉伺服日志显示：

- 视觉伺服启动时 `max_ratio=0.000`
- 连续搜索约 8 秒，没有确认有效目标
- 随后记录 `Target search timeout ... FAILURE`
- 未进入日志可见的冲刺阶段

结论：蓝球现场观察为**命中**，但自动视觉伺服日志没有确认命中；需要把现场观察与自动证据分开保存。

### 4.3 红球

试验目录：

`/home/ubuntu/cicc_v1_stage_20261005/baseline_tools/results/formal_trials/20261030T014137_red_V1/`

自动摘要：

- 总耗时：`216.383 s`
- 行为树结果：`ABORTED`
- 失败阶段：`cross_frame`
- `failure_reason=mission_result=ABORTED`
- 起飞、二维码识别成功；穿框、返框、打击、降落未被自动确认
- 模型实际生成的指令序列缺少 `cross_frame`：
  `takeoff → detect_aruco → return_cross_frame → hit_balloon:red → land`

现场观察：**用户观察到红球任务整体动作良好**。由于自动任务链被中止、且缺少 `cross_frame`，本轮不能作为完整的自动验收结果；现场观察应单独标记为人工观察结论。

## 5. 自动判据问题

1. `bt_ros.cpp` 对气球打击使用 `ForceSuccess`。视觉伺服失败或搜索超时后，行为树仍可能继续返航并发布 `SUCCESS`。
2. observer 的日志匹配对 `VisualServo` / `TargetTracker` 的大小写和文本形式不完整，导致实际出现 `FAILURE` 时 `hit_balloon_status` 仍为空。
3. `mission_success=false` 只能表示 observer 没有把所有阶段判为成功；`mission_success=true` 也不能单独证明指定气球已经破裂。
4. 红球一轮还暴露了自然语言到控制序列的不稳定：模型漏生成 `cross_frame`，使自动结果不能与前两轮直接横向比较。

## 6. 当前结论与后续建议

- 现场速度配置分类已完成：规划限速为 `0.30 m/s`，VisualServo 接近/冲刺为 `1.00/1.50 m/s`，冲刺时间 `1.20 s`。
- 三轮现场结论：紫球未命中；蓝球命中；红球现场观察良好但自动任务被中止。
- 三轮都不应只依据行为树 `SUCCESS` 宣称完成了指定颜色击破。
- 后续若修改代码，应优先：取消或细化打击阶段的 `ForceSuccess` 语义；修正 observer 对视觉伺服失败/成功的匹配；固定自然语言任务的必需指令序列；保留每轮遥测和现场证据。
