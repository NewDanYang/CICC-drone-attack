# 1.5 误击根因排查（改代码前，2026-10-18）

## 证据与判读口径

对 [1.1](../hit_balloon_part1_1.1/REPORT.md) 的两局和 [1.3](../hit_balloon_part1_1.3/REPORT.md) 的三局“3→1”逐条对齐 `scene_snapshots.jsonl`、`rosout_events.jsonl`、`observer.out` 与真实帧。时间均为 UTC。Actor 减少是**至少一只非目标球被删的下界**，不是物理碰撞的时间戳；`obj list` 需要 UE GC 才会及时反映销毁，[1.2 的连续 GC 实测](../hit_balloon_part1_1.2/REPORT.md)为 164 次采样、0 错误、约 1.83 秒间隔，而普通采样单例延迟 19.981 秒。下表五局均**未强制 GC**，直到 `settled`（任务后约 125 秒）才定结局。不同 `sim_pid` 的 Actor ID 不能跨实例解释颜色。

| 局（原始证据） | 任务结束 | Actor 时间序列 | 飞行与相机线索 | 是否证实靠近非目标球 |
|---|---|---|---|---|
| [1.1 蓝](../hit_balloon_part1_1.1/evidence/batch1/r1_blue_a1/scene_snapshots.jsonl)，[日志](../hit_balloon_part1_1.1/evidence/batch1/r1_blue_a1/rosout_events.jsonl)，[帧](../hit_balloon_part1_1.1/evidence/batch1/r1_blue_a1/real_frames/20261015T155135_710141Z_0095.jpg) | 15:52:36.439 | 15:52:38 `2`，15:52:54 `2`，15:53:24 `1`，15:54:45 `1` | 15:51:35 蓝球近景，**紫球远处同框**；15:52:24 视觉舵机结束并返航，15:52:30 `GoTo` 到起点。Actor 第二次减少发生在任务结束后 48 秒内，已无任务飞行。 | 只能证实同框，**不能证实无人机靠近紫球或红球**。无当前 UE 实例的 Actor 颜色映射。 |
| [1.1 紫](../hit_balloon_part1_1.1/evidence/batch2/r1_purple_a1/scene_snapshots.jsonl)，[日志](../hit_balloon_part1_1.1/evidence/batch2/r1_purple_a1/rosout_events.jsonl)，[帧](../hit_balloon_part1_1.1/evidence/batch2/r1_purple_a1/real_frames/20261015T163237_575652Z_0116.jpg) | 16:33:14.530 | 16:33:16 `1`，其后三次 `late` 与 `settled` 均 `1` | 16:32:37 紫球近景；16:32:38 后颜色分类开始报告红色，16:33:07 视觉舵机结束、返航。全局日志无冲刺与边界。 | **不能证实**。红色分类是检测 ROI 中的像素计数，既非该红球的世界位置，也非撞击证据。 |
| [1.3 紫](../hit_balloon_part1_1.3/evidence/batch1/r2_purple_a1/scene_snapshots.jsonl)，[日志](../hit_balloon_part1_1.3/evidence/batch1/r2_purple_a1/rosout_events.jsonl)，[帧](../hit_balloon_part1_1.3/evidence/batch1/r2_purple_a1/real_frames/20261015T173654_632825Z_0133.jpg) | 17:37:06.881 | 17:37:09 `1`，后续均 `1` | 17:36:54.257 在 `(3.431,-2.691,0.302)` 冲刺；0.597 秒后 `(2.818,-2.788,0.325)` 因目标面积激增刹车。此前近景为紫球；刹车后返航。无边界。 | **不能证实**哪只非目标球被擦碰，或碰撞发生在冲刺还是返航。 |
| [1.3 蓝 r2](../hit_balloon_part1_1.3/evidence/batch1/r2_blue_a1/scene_snapshots.jsonl)，[日志](../hit_balloon_part1_1.3/evidence/batch1/r2_blue_a1/rosout_events.jsonl)，[帧](../hit_balloon_part1_1.3/evidence/batch1/r2_blue_a1/real_frames/20261015T174223_711807Z_0107.jpg) | 17:43:19 左右（[observer](../hit_balloon_part1_1.3/evidence/batch1/r2_blue_a1/observer.out) 为准） | 17:43:21 `1`，后续均 `1` | 17:42:23 蓝球近景，17:42:24 镜头转向；17:43:08 视觉舵机超时结束。**无冲刺、无边界**。 | **不能证实**。这局直接反驳“误击都由冲刺后继续飞”这一单一解释。 |
| [1.3 蓝 r3](../hit_balloon_part1_1.3/evidence/batch1/r3_blue_a1/scene_snapshots.jsonl)，[日志](../hit_balloon_part1_1.3/evidence/batch1/r3_blue_a1/rosout_events.jsonl)，[帧](../hit_balloon_part1_1.3/evidence/batch1/r3_blue_a1/real_frames/20261015T180117_274528Z_0112.jpg) | 18:01:33 左右（[observer](../hit_balloon_part1_1.3/evidence/batch1/r3_blue_a1/observer.out) 为准） | 18:01:35 `3`，18:01:50 `1`，此后均 `1` | 18:01:17.669 蓝球占画面左侧时于 `(5.186,0.786,0.219)` 朝 `yaw=0.075` 冲刺；18:01:18.873 到 `(6.314,0.730,0.524)`，记录越界 1 次，之后返航。 | **不能证实**两只球各自的碰撞地点。15 秒后的双删与 GC 延迟兼容，却无法排除另一物理触发。 |

以上五局在第二次 Actor 减少的 `late` 时刻都已结束任务；B/C 两局**没有晚间新增飞行动作**。这支持“晚发现”可能性，不证明“每局任务中都曾靠近那只非目标球”。特别是 1.1 蓝帧里紫球在远处、1.3 蓝 r2 无冲刺，是原假说的未证实反例。没有同步气球世界坐标或本机遥测中对非目标球距离的标定，不能从这些证据反推出五局各自的碰撞时刻。旧 2/9、3/9 只是按 `settled` 口径得到的下界；不能声称真实误击率更高多少。

## GC 与空间信息

后续用 [`gc_timing_probe.py --mode continuous`](../../hit_balloon_v2/tools/gc_timing_probe.py) 在正式任务**开始前**启动，1.5 秒名义间隔持续 `obj gc` + `obj list`，直到任务结束并稳定；`--mode gc` 只在 `SPRINT_START` 后生效，会漏掉未冲刺的误击。GC 可能改变仿真时序，因此改前与改后都用相同模式、间隔、停止规则和开局三球要求。观察窗口内的每次计数变化及 Actor ID 保留原始 JSONL；结果表同时给传统 `after/settled`，两种口径不横比。

现有 [`scene_snapshot.py`](../../hit_balloon_v2/tools/scene_snapshot.py) 保存了 UE `obj list class=BP_Balloon_C` 的完整相关原始行；例如 [1.1 蓝的原始行](../hit_balloon_part1_1.1/evidence/batch1/r1_blue_a1/scene_snapshots.jsonl) 只有 Actor 路径、内存/资源数值，没有 `Location` 或 `Transform` 字段，**拿不到世界坐标**。1.1 蓝真实帧能同时看见蓝球近处、紫球远处；其余四局选取的接近帧只看见目标球，不能据此推断非目标球是否在镜头外的近旁。现有 1.4 配置 [A 与 C 的接近点同为 `5.3;1.0;0.7`](../hit_balloon_part1_1.4/REPORT.md) 是待测几何风险，不等于两个球的实际坐标。下一步如需距离结论，须通过带位置的 UE 查询或同一实例内的可复核标定取得气球坐标，再与遥测航迹逐时比对。

## 跟踪阈值核查

线上 `target_detector_base.cpp` MD5 `9e0af36ad105a51770c21c99d2732e3a`（2026-10-18 只读核对），在 [`findTargetInObjects`](../../../official_baseline/catkin_ws/src/mission_pkg/src/base/target_detector_base.cpp) 同时要求 `obj.class_name == target_class` 和 `obj.score >= confidence_threshold`。线上 `target_tracker.cpp` MD5 `d33701db820f199483b681a140ffd71e`，只平滑通过过滤的像素框。线上 [`det_color.py`](../../../official_baseline/catkin_ws/src/object_det/scripts/det_color.py) MD5 `348dd7d0ed3c66ce972c1e8158b3a07a`：先以 HSV 像素最多的颜色给 YOLO 框改名为 `red/blue/purple_balloon`，而 `obj.score = float(conf)` 沿用 YOLO **气球检测框置信度**。所以 `TargetTracker confidence_threshold="0.8"` **不是颜色置信度阈值**，但节点**确实检查颜色类名**；仅调高 0.8 不能直接修“认错颜色”。HSV 误分类仍可能让错误物体带上目标类名，需用同帧检测消息与原图证明，现有五局不足以确认。

## 根因排序与 1.6 单变量方案

1. **首位：航迹与附近非目标球的几何关系，包括目标之后的返航段。** 依据：五局跨三种 Actor 延迟模式、三局无冲刺也可双删；蓝球接近画面可见另一球，A/C 接近点重合。尚未取得非目标球位置，**这是优先调查的假说，不是已查明的根因**。1.6 先以同一 GC 口径复测旧版至少 3 局，并采集同步航迹/可用的气球位置；若证实 C 区进退路径靠近非目标球，只改 `llm_mission.launch` 的 C 区 `approach_pos`/`goal` 中必要的一组点，记录旧新坐标和逐局最近距离，单独验收。若 B 区也有同类证据，另起一批只改 B 区；A 区保持 1.4 状态。若非目标球位于**返航直线**，修复文件改为 `bt_ros.cpp` 中气球阶段之后的返航段，插入经实测安全的航点；不可仅凭想象改坐标。
2. **次位：HSV 误分类或多框切换导致跟踪目标换球。** `0.8` 是检测框分数，颜色只靠像素多数票。先收同时间戳 `/objects`、真实帧、`TargetTracker` 像素，查错色框是否以目标类名送入；若证实，单独改 `object_det/scripts/det_color.py` 的颜色可靠性判据或 `TargetTracker` 持续一致性，独立部署与验收。现阶段不盲调 `confidence_threshold`。
3. **再次：碰撞后继续飞。** 1.3 仅改 SPRINTING 后误击由 2/9 到 3/9（不同时间批次，均无强制 GC），而 1.1 蓝、紫和 1.3 蓝 r2 都无冲刺仍双删；不能优先把 1.3 判据照搬 APPROACHING。只有连续 GC + 同步位置证明目标接触后仍沿非目标方向前进，才单独补 `visual_servo.cpp` 的 APPROACHING 提前悬停。

**结论范围**：五局、原场景、A0、旧版非强制 GC；没有随机化、没有气球世界坐标、没有逐 Actor 颜色真值。此报告先于 1.6 任何源码修改完成；后续证据若推翻排序，在 1.6 报告记录变更理由，不改写这里的原始观察。

## 补充：1.6 动源码前的同口径三色对照（2026-10-18）

在线仍为 1.4 红区配置、原版 `visual_servo.cpp`，三色各一局；每局开局三 Actor，`gc_timing_probe.py --mode continuous --interval 1.5` 从正式任务前运行到任务后 3 秒，结局再等 125 秒。三局均 0 采样错误。原始目录：红 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T002752_red_A0/`，紫 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T003354_purple_A0/`，蓝 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T003953_blue_A0/`，每目录含 `gc_continuous/events.jsonl`、正式遥测、真实帧、场景快照；循环汇总 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_gc_control_20261018/trials.csv`。

| 目标 | GC/Actor 样本 | GC 计数转变（UTC，区间上限） | 125 秒结局 | 现场判断 |
|---|---:|---|---:|---|
| 红 | 85/85 | 16:29:37.354–39.186，3→2 | 2 | 无额外删球 |
| 紫 | 79/79 | 16:35:59.155–16:36:00.985，3→2；16:36:13.797–15.628，2→1 | 1 | **先删非目标**：第一次在视觉舵机刚开始、机体约 `(5.52,-2.16,0.38)`，紫球仍在 [16:36:00.501 的真实帧](evidence/control_purple_first.jpg)远处。随后 16:36:14.436 朝紫球冲刺，第二次删球前 [16:36:14.299 的帧](evidence/control_purple_second.jpg)紫球已近景。第一删球与 B 区旧接近点 `5.3;-2.0;0.7` 同一区域。 |
| 蓝 | 90/90 | 16:41:29.606–31.439，3→2；16:42:02.787–04.622，2→1 | 1 | 第一次紧随蓝球跟踪开始；第二次发生于 50 秒搜索期间，期间颜色分类 16:41:41 显示红色大面积（非独立碰撞证明）。 |

紫局机体位置由同局 `/mavros/local_position/odom` 样本映射至 `VisualServo` 使用的平面轴得出；原始遥测位于上述紫局正式目录的 `*telemetry.jsonl`，[取样脚本](../../hit_balloon_v2/tools/odom_at_times.py)可重做对齐。16:36:00.993 样本的原始位置 `x=2.1557,y=5.5188,z=0.3750`，与 ROS 日志里位置轴互换且一轴反号。第一次删球时紫球仍被相机看见，故“第一次是目标紫球”与该帧及后续持续紫球近景矛盾。这一局首次把**非目标在接近点附近先被碰到**从假说提升为有时序支撑的结论；不能由 1 局外推所有 B 局。蓝局先有[蓝球近景](evidence/control_blue_before.jpg)，随后[破裂亮光](evidence/control_blue_flash.jpg)，再有[红球近景](evidence/control_blue_red_near.jpg)；[第二次删球窗口的帧](evidence/control_blue_after.jpg)已转离红球，因此无法从相机直接标定第二个 Actor 颜色。第二次删球确实发生在搜索状态，说明 B 的修复不会自动解决 C。

尝试用 RflySim SDK `reqObj` 只读查询三只 Actor 的 `PosUE`；同一实例的三只中仅一只返回，且其 x 随时间移动（约 `4.63→2.75→4.94`），因此无法计算三球完整的静态间距。`obj list` 本身亦无位置列。**1.6 的第一单变量修复确定为仅改 `llm_mission.launch` 的 B 区 `approach_pos` 和 `goal`，将同一个入场位置从 `5.3;-2.0;0.7` 移到 `3.5;-2.4;0.7`**，使入场点相对已观测首删球位置在平面上远离约 2 m，同时保持朝紫球的 B 区 yaw 和 A/C 原值。两参数共同表达同一个 B 区入场位置，否则后续 `GoTo` 会回到旧危险点。先独立测试紫局，再决定 C 区的单独修改。
