# 1.7 三色九局全量验收（2026-10-18）

## 版本与口径

本轮使用 [1.6 部署记录](../hit_balloon_part1_1.6/REPORT.md)中的 B-v2 入场点（线上 `llm_mission.launch` MD5 `fbc7556d8e0506563152e8eac9ec69f5`）与蓝球近距丢帧后退出搜索（线上 `visual_servo.cpp` MD5 `5a9bb56d2fef2aa3127c3a61bb153656`）。A 区仍为 1.4，其他 B/C C++ 和安全边界未改。每局开局先用 UE `obj list` 验证 3 Actor，不足时等 PX4 解除武装再 `reset_scene_checked.sh` 重启；正式试验前启动 `gc_timing_probe.py --mode continuous --interval 1.5`，任务结束后延续 3 秒并在约 125 秒后取 `settled`。原始连续 GC 事件包含每次采样的时间戳、Actor ID 与 UE 原始行。`runner_rc` 和 `mission_success` 与物理删球分开统计。

改前同口径对照为 [1.5 三色各一局](../hit_balloon_part1_1.5_root_cause/gc_control_summary.csv)：红 `3→2`、紫 `3→1`、蓝 `3→1`，GC 采样 `85、79、90` 次且无错误；边界 `0、2、0`。改前紫/蓝的飞行代码与 1.1 相同，红区采用 1.4；因此它是三局的同时期连续 GC 对照，**不是**历史 1.1 无强制 GC 九局的同口径复算。比较只适用于本服务器、本场景、A0 档位和这一采样策略。

## 九局逐局证据

第一批正式目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_full_acceptance_20261018/`，循环 `exit_code=0`。每行正式目录含 `gc_continuous/events.jsonl`、`scene_snapshots.jsonl`、`observer.out`、真实帧 `real_frames/` 与原始遥测。[逐局原始 GC 汇总](batch1_gc_summary.csv)保留正式目录路径和所有变化时戳；[精简原始证据包](batch1_evidence.tar.gz)包含九局 `events.jsonl`、场景快照、相机索引、变化时窗真实帧、观察器和 ROS 日志。包内 `manifest.json` 列出未裁剪的服务器原始目录。全部九局 `before_count=3`、`valid=1`，合计 **739 次 GC / 739 次成功 Actor 采样 / 0 错误**。

| 轮次 | 红：GC 变化，边界 | 紫：GC 变化，边界 | 蓝：GC 变化，边界 |
|---|---|---|---|
| 1 | `3→2`，0 | `3→2`，1 | `3→2`，0 |
| 2 | `3→2`，0 | `3→2`，3 | `3→2`，0 |
| 3 | **`3→2→1`，0** | `3→2`，2 | `3→2`，0 |

第一轮蓝球在 [蓝球近景](evidence/r1_blue/blue_near.jpg)后 [蓝球消失](evidence/r1_blue/after.jpg)，后续同局 [红球和紫球仍在画面](evidence/r1_blue/red_purple_remain.jpg)。`BLUE_NEAR_CONTACT_LOSS_COMPLETE` 于 17:50:17.093 UTC 触发，GC 的 `3→2` 于 17:50:15.229–17:50:17.061 UTC 被发现；没有第二次删球。第二、三轮蓝球均 `3→2`、无边界；第二轮正常冲刺，说明这一修复并非每局必经的成功路径。

第三轮红球的 **两次删球是明确误击**：GC 分别于 18:13:44.321–46.150 UTC、18:13:55.293–57.122 UTC 检出删球。第一次时机体约在 `VisualServo` 坐标 `(5.35,0.91,0.41)`、速度接近零，[红球仍在眼前](evidence/r3_red/red_still_visible_at_first_loss.jpg)。第二次之前有[红球冲刺近景](evidence/r3_red/red_sprint.jpg)，随后 [破裂光点](evidence/r3_red/red_flash.jpg)；返航时[紫球仍可见](evidence/r3_red/purple_survivor.jpg)。同一 UE 实例里第一只删的是蓝球、第二只是红球；不依赖跨实例 Actor ID 映射。首删点与 A/C 共用入场点 `5.3;1.0;0.7` 的水平距离约 0.1 m，且发生在红球冲刺前，证实这局是**红区入场附近先误击蓝球**。它不证明所有旧红局都如此。

三局紫球各一次 `3→2`，但边界触发 `1、3、2` 次，共 **6 次 / 3 局**。安全恢复日志六次均记录机体 `y≈-3.00` 或 `-3.01 m`，越过未改的 `safety/y_min=-3.0 m`；第二轮第一次触发在目标删球约 19 秒前，故不能用“击破后仍搜索”解释全部越界。B-v2 入场点 `4.3;-2.4;0.7` 的走廊距离 y 边界较近。第二轮三次记录在该局原始遥测 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T015945_purple_A0/*telemetry.jsonl`，可按 18:01:26.350、34.750、45.830 UTC 重查；第三轮两次在 18:19:28.450、32.650 UTC。

## 四项验收与局限

第一批四项指标：三球开局 **9/9 通过**；零误击 **失败，至少 1/9 红局误删蓝球**；零同局删两球 **失败，1/9**；边界 ≤1/9 局 **失败，3/9 局，合计 6 次**。因此第一批明确 **未通过验收**。同口径改前对照仅三局，曾有紫/蓝各一局 `3→1`、紫球两次边界；新旧样本量不同，不能用本批蓝球 `0/3` 额外删球断言真实误击概率归零。红球反例亦说明 `3→2` 不足以独立证明击破了目标；其余颜色身份只按各自真实帧的证据强度陈述，不跨实例套 Actor ID。

9 局 BT 返回成功，观察器 `mission_success=true` 为 4/9。其余 5 局观察器的 `hit_balloon_status` 为空且 `notes` 写明 `SUCCESS received while stages were unobserved: hit_balloon`；这是阶段事件记录缺口，不能当作五次物理击球失败，也不能忽略为完全成功。本验收以题定四项物理/边界指标判定。

针对第一批可独立复现的两个故障，下一批只把 B 区入场点 y 从 `-2.4` 改到 `-2.0`，保持 A/C 与 C++ 不变，先做紫球三局；之后才单独把 A 区入场走廊从 y=`1.0` 移离蓝球附近，做红球三局。两项修复不能混在同一独立试验批里。全部原始证据保留，下一次九局若运行，将作为新版本另列，不覆盖本批。

## 第二批：B-v3、A-v4、蓝球近距退出

1.6 中 B-v3 紫球独立三局 `3/3` 正确删球、`0/3` 边界；A-v4 红球断线前两局与恢复后三局合计 `5/5` 正确删红、`1/5` 边界。为检验组合，保持线上 `llm_mission.launch` MD5 `5550c580a4822e773a331bcef11f0c47`、`visual_servo.cpp` MD5 `5a9bb56d2fef2aa3127c3a61bb153656`、`bt_ros.cpp` MD5 `0ce0f6ec147d516d20e1a89d612792a6`，在新 UE 三球场景按红紫蓝顺序各跑三局。正式批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_full_acceptance_v2_20261018/`，循环 `exit_code=0`；[逐局 GC 汇总](batch2_gc_summary.csv)及[原始证据包](batch2_evidence.tar.gz)保留九局正式目录、连续 GC、逐局场景快照、真实相机变化时窗、观察器和 ROS 日志。九局均 `before_count=3`、`valid=1`，合计 **738 次 GC / 738 次成功采样 / 0 错误**。

| 轮次 | 红：GC 变化，边界次数 | 紫：GC 变化，边界次数 | 蓝：GC 变化，边界次数 |
|---|---|---|---|
| 1 | `3→2`，0 | `3→2`，2 | `3→2`，1 |
| 2 | `3→2`，0 | `3→2`，0 | `3→2`，1 |
| 3 | `3→2`，0 | `3→2`，0 | `3→2`，0 |

九局均只有一次 `3→2` 且 `settled=2`，无同局第二次删球。逐局真实帧在变化窗口显示指定色气球接近后消失或出现破裂光点，例如[第一轮紫球近景](evidence_v2_r1_purple/purple_near.jpg)与[消失](evidence_v2_r1_purple/purple_gone.jpg)、[第一轮蓝球近景](evidence_v2_r1_blue/blue_near.jpg)与[消失](evidence_v2_r1_blue/blue_gone.jpg)、[第三轮红球近景](evidence_v2_r3_red/red_near.jpg)与[消失](evidence_v2_r3_red/red_gone.jpg)；其余六局的变化时窗帧在证据包内。颜色判断依据**本局画面**，不复用其他 UE 实例的 Actor ID。按这一口径本批零确认误击、零 `3→1`。但第二批边界触发 **3/9 局、合计 4 次**，超过 ≤1/9 局，故仍 **未通过全量验收**。红球 0/3、紫球 1/3、蓝球 2/3 边界。紫球第一轮在追踪搜索时 `(4.83,-3.02,0.07)`、冲刺结束时 `(-0.06,-3.01,0.18)` 越过 y 下界；蓝球第一、二轮在目标删球后返航 GoTo 阶段分别到 `x=-1.01`、`x=-1.09 m`，越过 x 下界。这是两种不同飞行时段的触发，第三轮蓝球未触发。安全边界默认值没有变。

九局 BT 均返回成功，但观察器 `mission_success=true` 仍只有 4/9；其余 5 局均缺独立的气球阶段事件，不能以 `3→2` 代替整局得分确认。与[同口径旧版对照三局](../hit_balloon_part1_1.5_root_cause/gc_control_summary.csv)的紫、蓝各一次 `3→1` 相比，本批九局没有复现额外删球；对照样本只有三局、版本也含 1.4 红区，结论只适用于本服务器、A0、连续 GC 与上述候选，不外推长期误击率。下一步单独限制**降落返航 GoTo** 的远距离位置设定点，保持 B-v3/A-v4、视觉舵机及安全边界不变，先用蓝球独立试验检验 x 方向过冲是否消失，再做新的三色九局；紫球边界反例仍需由新批实际结果判定。

## 第三批：返航限距、蓝球降速及收紧近距退出

在第二批后，1.6 先后单独部署返航 GoTo `setpoint_lookahead=0.6 m`、蓝球冲刺速度 `1.0 m/s`（红紫仍 `1.5 m/s`）、蓝球近距丢失完成所需历史最大面积 `>=0.30`，各自有独立蓝球三局和部署记录；其中蓝球降速单独批曾出现 `3→3` 漏击，收紧判据后独立三局均 `3→2`、边界 0。第三批组合验收时线上 MD5：launch `5550c580a4822e773a331bcef11f0c47`、`visual_servo.cpp` `ae8e6172e4ddbfc851bcfdf080dc2aec`、`bt_ros.cpp` `6ba77aa30eb4c42588d064820bcf852d`、`goto.cpp` `f557ace5bbf2ee7975b7335a738ffcf9`。B-v3、A-v4 坐标及安全边界默认值未变。

正式批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_full_acceptance_v3_20261018/`，循环 `exit_code=0`。九局均 `before_count=3`、`valid=1`，全程相同 `gc_timing_probe.py --mode continuous --interval 1.5`；[逐局 CSV](batch3_gc_summary.csv)和[原始证据包](batch3_evidence.tar.gz)保存正式目录、707 次连续 GC 采样（错误 0）、场景快照、真实帧、观察器及 ROS 日志。各局 `settled` 与 GC 终值一致：

| 轮次 | 红：GC 变化，边界次数 | 紫：GC 变化，边界次数 | 蓝：GC 变化，边界次数 |
|---|---|---|---|
| 1 | `3→2`，0 | `3→2`，0 | **`3→3`，1** |
| 2 | `3→2`，0 | `3→2`，1 | `3→2`，0 |
| 3 | `3→2`，1 | `3→2`，1 | **`3→2→1`，0** |

六局红/紫的目标颜色逐局由真实帧核对：例如[第一轮红球近景](evidence_v3_r1_red/red_near.jpg)与[下一帧消失](evidence_v3_r1_red/red_gone.jpg)、[第一轮紫球近景](evidence_v3_r1_purple/20261018T050814_952563Z_0122.jpg)与[消失](evidence_v3_r1_purple/20261018T050816_029686Z_0123.jpg)、[第三轮紫球近景](evidence_v3_r3_purple/purple_near.jpg)与[消失](evidence_v3_r3_purple/purple_gone.jpg)；其余变化时窗在证据包内。第二轮蓝球 `3→2` 的正式观察器也确认整局成功。第三轮蓝球[蓝球近景](evidence_v3_r3_blue/blue_near.jpg)后[蓝球消失、紫球仍在](evidence_v3_r3_blue/blue_gone_purple_present.jpg)，GC 于 05:48:01 UTC `3→2`；返航中 05:48:10 UTC 再 `2→1`，05:48:14 UTC 的[后续帧仍能看到紫球](evidence_v3_r3_blue/purple_survivor.jpg)，所以第二只被误击的是红球。该时段机体约 `(0.56,0.75,0.36)`；这项颜色判断来自**同一局**画面与 GC 时序，并未跨重置复用 Actor ID。

第一轮蓝球是另一个反例：冲刺 `1.0 m/s × 1.2 s` 从 `(5.256,0.781,0.309)`、yaw `-0.198` 开始，到 `(5.907,0.567,0.525)` 时蓝球还在画面右缘，随后机体到 `x=6.01` 触发 x 上界；任务后及 `settled` 始终 `3→3`。[冲刺时蓝球仍完整](evidence_v3_r1_blue_miss/20261018T051416_195402Z_0104.jpg)和[转向墙面后的画面](evidence_v3_r1_blue_miss/20261018T051418_316078Z_0106.jpg)保留反例。第二轮紫球边界在删球后返航时 `x=-1.00`；第三轮红球冲刺结束 `x=-0.147` 后立即返航，约 1 秒到 `x=-1.00`；第三轮紫球在追踪阶段 `y=-3.01`，返航尚未开始。这四次分别归属 4 局、4 个事件，涉及蓝球入场、紫球追踪和返航制动，不能归为同一个故障。

四项验收：三球开局 **9/9 通过**；零误击 **失败，至少 1/9 蓝局误删红球**；零同局删两球 **失败，1/9**；边界 ≤1/9 局 **失败，4/9**。指定球物理击破为 **8/9**，但其中一局又误击红球，因此“恰好击破指定球”为 **7/9**。BT 成功 9/9，观察器整局成功 6/9；观察器的阶段事件缺失仍须与物理 GC 分开解释。本批只代表 A0、本服务器与连续 GC 小样本，不能外推长期成功率。基于第一轮蓝球 x 上界与第三轮蓝球返航误击，将先单独验证 C 入场位置，再单独处理返航路线；不把两项同时改后的一批冒充单变量证据。

## 第四批：蓝球返航航点与冲刺后可见目标重对准

第三批以后，1.6 分别做了 C 入场向内移动、蓝球返航绕行、蓝球冲刺后可见目标重对准及 B 入场再向内移动的独立试验。C 候选出现误击并回滚，B 再向内候选出现漏击和边界并回滚。第四批使用 A-v4/B-v3/C 原入场，蓝球返航航点和重对准候选；线上 MD5：`llm_mission.launch` `5550c580a4822e773a331bcef11f0c47`、`visual_servo.cpp` `a63b57fa127a23cd8bb8e647f078ff21`、`bt_ros.cpp` `9b1cefe9dfa431418435f7f8f63a60ed`、`goto.cpp` `f557ace5bbf2ee7975b7335a738ffcf9`。安全边界默认值未改。

正式批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_full_acceptance_v4_20261018/`，循环 `exit_code=0`；[九局 CSV](batch4_gc_summary.csv)和[原始证据包](batch4_evidence.tar.gz)保存每局连续 GC 原始事件、场景快照、观察器、ROS 日志及变化窗口真实帧。每局 `before_count=3`、`valid=1`；合计 **736 次连续 GC / 736 次成功采样 / 0 错误**，间隔 1.5 秒，同[旧代码对照](../hit_balloon_part1_1.5_root_cause/gc_control_summary.csv)口径。九局终值都为 2，且各只有一次 `3→2`：

| 轮次 | 红：GC 变化，边界次数 | 紫：GC 变化，边界次数 | 蓝：GC 变化，边界次数 |
|---|---|---|---|
| 1 | `3→2`，0 | `3→2`，1 | `3→2`，0 |
| 2 | `3→2`，0 | `3→2`，3 | `3→2`，0 |
| 3 | `3→2`，0 | `3→2`，2 | `3→2`，0 |

颜色判读来自每局自己的相机变化窗口，而不是跨 UE 实例复用 Actor ID：[首轮红球近景](evidence_v4/r1_red_near.jpg)→[消失](evidence_v4/r1_red_gone.jpg)、[蓝球近景](evidence_v4/r1_blue_near.jpg)→[消失](evidence_v4/r1_blue_gone.jpg)；第二轮[红球](evidence_v4/r2_red_near.jpg)→[消失](evidence_v4/r2_red_gone.jpg)、[紫球](evidence_v4/r2_purple_near.jpg)→[消失](evidence_v4/r2_purple_gone.jpg)、[蓝球与远处紫球同框](evidence_v4/r2_blue_near.jpg)→[蓝球消失](evidence_v4/r2_blue_gone.jpg)；第三轮[红球](evidence_v4/r3_red_near.jpg)→[消失](evidence_v4/r3_red_gone.jpg)、[紫球破裂光点](evidence_v4/r3_purple_flash.jpg)、[蓝球](evidence_v4/r3_blue_near.jpg)→[消失](evidence_v4/r3_blue_gone.jpg)。首轮[紫球冲刺近景](evidence_v4/r1_purple_near.jpg)与唯一 GC 删球同窗。原始证据包提供各窗口的全部连续帧，以上图片只是便于复核的摘取。本批 **没有观察到非目标球被删，也没有同局第二次删球**；这只适用于本批九局，不是长期零误击率证明。

边界反例均在紫球，且有不同阶段。第一轮紫球 `SPRINT_START` 于 13:45:55.593 UTC，位置 `(0.913,-2.789,0.271)`、yaw `-2.956`、速度 1.5 m/s；1.2 秒后冲刺结束在 `x=-0.333`，惯性延续到 13:45:57.569 UTC 的 `x=-1.02`，触发 x 下界。第二轮紫球在近景后消失，GC 于 14:03:50.767 UTC 唯一删球；视觉舵机 14:03:50.234 UTC 仍把丢目标搜索锚在 `y=-2.917`，随后 14:03:51.609、55.329、59.610 UTC 三次到 `y≈-3.00`。安全恢复把机体拉向 `y=-2.70`，但仍运行的搜索持续发送原锚点，造成反复触发。第三轮紫球首次触发在**接近阶段**：目标画面面积从 0.3% 增到 57.9%，1.0 m/s 的前进命令到近距才归零；真实仿真里程计从 `y=-2.32` 走到 `-3.02`，14:21:16.409 UTC 首次触边，14:21:17.700 UTC GC 删球；之后搜索锚点又记录 `y=-2.997`，14:21:20.209 UTC 第二次触边。因此只改丢目标搜索锚点不能覆盖第三轮第一次触边，只改冲刺也不能覆盖第二、三轮。

四项验收：三球开局 **9/9**；按同局帧与连续 GC 判读，确认误击 **0/9**；同局删两球 **0/9**；边界触发 **3/9 局、共 6 次，超过 ≤1/9**，所以第四批**未通过**。BT 返回成功 9/9，观察器 `mission_success=true` 4/9；其余五局存在独立气球阶段事件未记录的缺口，不能把物理删球直接说成整局拿分。与旧代码连续 GC 对照 n=3 的紫、蓝各一次 `3→1` 相比，本批九局没有复现额外删球；样本量和代码版本均不同，结论只限这台服务器、A0、此场景和 1.5 秒连续 GC。

下一步按独立变量处理紫球：先把接近速度从 1.0 降至 0.6 m/s 验证接近阶段惯性，再单独处理丢目标搜索锚点和冲刺速度；每步保留三球开局与连续 GC，不把这些改动合并成一次单变量试验。当前候选部署及独立结果见 1.6 后续记录。

## 回滚

见 [1.6 回滚命令](../hit_balloon_part1_1.6/REPORT.md#回滚)。
