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

## 回滚

见 [1.6 回滚命令](../hit_balloon_part1_1.6/REPORT.md#回滚)。
