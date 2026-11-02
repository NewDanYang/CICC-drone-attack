# 任务书：v5 "Never Blind" —— 让九格 FM9G 真正进入击球闭环

> **状态更新（2026-11-02）**：本任务书未交付执行——用户指示由实验员本人上机（Astra 用量爆满）。
> 实际执行结果见 [`../v6_servo_closed_loop/REPORT.md`](../v6_servo_closed_loop/REPORT.md)。

> 交给 Astra 执行。写这份任务的是实验员（已完成离线诊断，未上机）。
> **先读 `v5_never_blind/REPORT.md`**，那里有全部数字、证据路径和每条设计的理由。
> 你要做的是把它实现、上机验证、给出 A/B 数据。不要重新做已经被证伪的实验。

---

## 0. 你的角色与边界

- 你是执行者：按阶段实现 → 自测 → 上机 → 报数。**创新方案已经给定，不要自行改变架构方向**；
  遇到设计没覆盖的细节，按"最小改动、可回滚、不碰安全边界"的原则决定，并在报告里写清。
- 这是真实比赛系统。**任何"看起来好了"都不算数**，只认数字、样本数、对照组。
- 服务器现在归你用（负责人已停掉另一个 agent），但仍要遵守 §2 的锁与环境纪律。
- 允许：改 `/home/ubuntu/multimodal_v2/` 下的桥接代码、改 `catkin_ws/src/mission_pkg` 下的
  `multimodal_target_tracker` 与 `visual_servo`、重启节点、跑正式试验、编译。
- 禁止：改比赛规则禁止项、改 v1 安全边界默认值、删除他人数据、推 main 分支、
  在环内引入 HSV/YOLO 等任何"非九格"检测器（见 REPORT §L5）。

---

## 1. 一句话背景

FM9G 识别没错，是**桥接层**把它用错了：78% 时间没有框、决策 0.9 s 陈旧、2 Hz、
偶尔给出贴边假框，30 Hz 的 VisualServo 因此振荡、黑屏盲转、甚至被假框按到地上（z=0.1 m）。
36 局对比 14/18 vs 18/18。方案 = **语义低频、几何高频、永不黑屏**。

---

## 2. 环境与纪律

### 2.1 访问

```bash
export TCEI_HOST=120.209.70.195 TCEI_PORT=30316 TCEI_USER=root
# TCEI_PASSWORD 由项目负责人提供；不要写进任何会进 git 的文件
cd <repo>
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh "命令"     # Windows 必须带这个前缀
python v3_stability/tools/srvctl.py put 本地 远程
python v3_stability/tools/srvctl.py get 远程 本地
```
SSH 偶发掉线：用 srvctl（已内置重试），不要裸 scp。

### 2.2 锁与环境

- 每轮试验前：`ls -d /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock 2>/dev/null`，
  有残留先确认 PID 已死再清（`cat <lock>/pid`）。
- 起环境：`export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority`，
  `setsid nohup bash /home/ubuntu/tcei_baseline_tools/start_sim_environment.sh`，
  等日志出现 `environment_started=1`（2–4 分钟）。
- **改代码前必须备份 + 记 md5**，报告里给回滚命令（AGENTS.md §3.3）。
- 不要用 `pkill -f 脚本名`（会自杀），用 `pgrep -f "[a]ruco_detect_node"` 或按 PID。

### 2.3 关键路径

| 用途 | 路径 |
|---|---|
| 部署的桥接代码 | `/home/ubuntu/multimodal_v2/p12e_stage_b/v2/`（runtime.py / presence.py / tracking.py） |
| 部署备份 | `/home/ubuntu/multimodal_v2_backup_20261026T0009` |
| 部署/回滚工具 | `/home/ubuntu/multimodal_v2/p12e_stage_b/patches/deploy_v2.py`（先跑 `status` 看懂它） |
| 条件开关 | `/home/ubuntu/multimodal_v2/tools/switch_condition_v2.sh <condition> <backup> [no-reset]` |
| C++ BT 节点 | `/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp`（+ include 同名 .h） |
| 视觉伺服 | `/home/ubuntu/catkin_ws/src/mission_pkg/nodes/action/visual_servo.cpp`（+ include/nodes/action/visual_servo.h） |
| 编译 | `cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg`（C++ 改动后必须） |
| 单局 | `/home/ubuntu/tcei_baseline_tools/run_formal_trial.sh {red|purple|blue}` |
| 观测工具 | `/home/ubuntu/tcei_hit_balloon_v2_tools/`（scene_snapshot.py / judge_hit.py / capture_real_frames.py / reset_scene_checked.sh） |
| 试验编排（照抄） | `v4_innovation_timing/multimodal_5_12_stage_d_repeat/tools/*.sh` |

### 2.4 数据通路（改代码前先确认）

```
FM9G python runtime ──/multimodal/objects (common_msgs/Objects, frame_id="fm9g:<session>:<decision>")──▶
  MultimodalTargetTracker (C++ BT 节点)：age>0.35s 或前缀不符 ⇒ is_detected=false；
                                          默认 3 帧滑动平均；score<threshold 丢弃
  ──PixelTarget──▶ VisualServo (C++)：err→yaw_rate/vz，data_timeout=1.0s，面积≥0.08+居中 ⇒ sprint
```
`/multimodal/balloon_target` (std_msgs/String JSON) 是 BT 通知 Python 开始/停止的闸门。

---

## 3. 分阶段执行（每阶段先备份，出口条件不过就不进下一阶段）

### P0 复现（半天）

1. 确认部署 md5 与 `switch_condition_v2.sh status` 一致；记录 `runtime.py` 的 md5。
2. 找到 audit 落盘位置：`grep -n "audit" /home/ubuntu/multimodal_v2/p12e_stage_b/v2/runtime.py`。
3. 跑 1 局紫候选 + 1 局紫基线（用 5_12 的编排脚本，别手搓）。
4. 用 `.scratch/fm2/blackout3.py` 的逻辑复现"带框发布 60 次 / 空档 4 个 >1.0 s / 最长 20 s"。
   **出口**：你独立算出的黑屏比例与 78% 相差 ≤5 个百分点。算不出就先查 audit 是否在写。

### P1 L1 连续性（纯 Python，最高收益）

改 `runtime.py` 的发布路径（参考行：`publish_current=(None if self.track_misses else ...)` 在 306–307，
发布在 329–349）：

1. 新增预测状态：`last_box / last_box_t / vx, vy (px/s) / K (px/rad)`。模型来新框时 α-β 校正
   （α=0.6, β=0.15），否则每帧外推。
2. 偏航补偿：订阅 `/mavros/local_position/odom`，取 `twist.twist.angular.z`（rad/s），
   每帧 `cx -= K*omega*dt`；K 初始 326，用 (Δu, ∫ωdt) 在线最小二乘更新，钳制 [150, 800]。
3. 状态机：新框 → TRACKING；<0.6 s 无新框 → HOLD（继续发，score 1.0→0.31 线性衰减）；
   >0.9 s → LOST（**不发**，让 data_timeout 正常触发，同时立刻发起全图瓦片扫描）。
4. 框尺寸在 HOLD 期间冻结（不要外推尺寸，否则 8% 面积判据会被污染）。
5. BT 端口 `filter_window_size` 3 → 1（在 BT/launch 里改，不动默认值以外的东西）。

**自测（不上机）**：把一局真实 audit 的模型框序列灌进一个纯 Python 桩，检查
(a) 相邻发布间隔 p95 ≤0.1 s；(b) 预测框与下一个真框的偏差中位数 ≤20 px。
**上机**：3 局紫色。**出口**：G2 = 0 次 >0.9 s 空档、p95 反馈龄 ≤0.35 s。

> 注意：当前跟踪器每来一个模型框就 initialize+replay，会重置内部状态。P1 必须改成
> "跨框维持 + 位置偏移校正（|Δ|>40 px 才重播种）"，否则预测与跟踪器互相打架。

### P2 L2(校验) + L3(近距)

1. 贴边：框贴 `x≤2 / x2≥637 / y≤2 / y2≥477` 时，把该方向中心替换为上一有效值（或 320/240），
   记 `clipped`；**clipped 框不得改变 sprint 判据**。
2. 碎片：面积 < 预测面积 ×0.45 ⇒ 用预测框续发，不用新框。
3. 跳变：0.25 s 内中心跳 >120 px ⇒ 拒绝该框。
4. 自适应窗：窗 = clamp(2.2×上次框, 96, 320)，中心用预测位置。
5. 饱和：四条剖面都未在窗内跌破阈值 ⇒ 整窗当框发布（score 0.6）。
6. 二级细化：224 窗 → 96 窗复扫 8 个位置。

**上机**：3 局紫。**出口**：近距离（气球占画面 >5%）时发布的框面积 ≥ 窗面积 60%，
且出现至少一次 sprint 触发（日志里能看到 SPRINTING）。

### P3 L2(高度下限)

`visual_servo.cpp` 增加 ROS 参数 `min_altitude`（默认 0.0，阶段 D 的 launch 设 0.35）：
`onRunning()` 里 z 已低于下限且 `vz<0` ⇒ `vz=0` 并 `ROS_WARN_THROTTLE` 一次。
`catkin_make --pkg mission_pkg`，重启 llm_mission_node。
**上机**：3 局紫。**出口**：G1 = 0 次 z<0.30（用 rosout 的 SEARCH_ANCHOR / 遥测核对）。

### P4 L4 预算与调度

1. 决策永远用最新帧（删锚点帧配对那 0.38 s 缓冲）。
2. 稳态：0.7–1.0 s 一次模型调用，5–13 图（验证预测窗 + 细化）。
3. 丢失：15 图瓦片 + 两级扫描。
**出口**：单次决策 latency ≤0.25 s（audit 的 `latency_s`），反馈龄 p95 ≤0.2 s。

### P5 A/B 18 局（正式收数）

- 协议照抄 `multimodal_5_12_stage_d_repeat_collect.sh`：每行 `switch_condition → reset_scene_checked →
  start_env → trial`，候选/基线交错，每色 3 候选 + 3 基线（共 18 局）。
- **必须**每局记录 manifest：pair / color / condition / trial_rc / trial_dir / runtime md5 / 时间戳。
- 判读用 `judge_hit.py` + `scene_snapshots.jsonl`；不要凭肉眼。
**出口**：G1–G5 全过（REPORT §4）。任何一门不过，先修再重跑，不要"挑几局好看的报"。

### P6 合规物（可与 P5 并行）

- bbox 视频（阶段 D 全过程，能看清框）——规则 4.4(5) 要求展示。
- 多类别识别展示：一个**只显示、不控制**的节点，把气球/障碍物/方形障碍/起降标识/烟雾弹都框出来录屏
  （规则 `规则.txt:222` 要求全部类别）。
- 技术文档：架构图、机制、A/B 数据、回滚方式。

---

## 4. 报告要求（每阶段一份，放 `v5_never_blind/runs/<日期>/`）

- 原始证据路径（audit jsonl、rosout、trial_dir），不只写结论。
- 样本数 + 对照组 + 指标定义（"3 局中 2 局"不是"修复有效"）。
- 明确区分：算法改动 / 环境偶发 / 大模型输出异常（AGENTS.md §6.7）。
- 回滚命令 + 改动文件 md5。
- 结论的适用范围（单色单档位的结论不要外推）。

失败也要写：哪一门没过、数字多少、你判断的原因、下一步打算。**不要为了让数字好看而改判据。**

---

## 5. 停止条件（遇到就停下找我）

1. P5 后 G3 <17/18，且失效原因已确认**不是**黑屏/坏框（即框质量本身不够）。
   ⇒ 不要自己开训练任务，把 audit + 失败局帧交回实验员。
2. 需要改规则、改安全边界默认值、或需要 24 h 以上的训练算力。
3. 服务器 SSH 连不上（banner 掉线超过 10 分钟）——这不是你的问题，报告里写明即可。
