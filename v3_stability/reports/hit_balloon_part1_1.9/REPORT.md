# 第一部分：唯一单变量复测，提前否决并回滚（2026-10-19）

## 试验设计与结论

首批九局在[新标准报告](../hit_balloon_part1_1.8/REPORT.md)中有 8/9 指定球击破、零误击、零双删，但紫色第二轮的触边帧有疑似贴墙，未通过五项全部指标。依据[墙面实测](../hit_balloon_part1_boundary_survey/REPORT.md)，本次**只修改一个数值**：`safety/y_min=-3.0 → -2.20 m`，其余 A-v4/B-v3/C 原入口、蓝球返航 via/可见重对准、C++/Python 均保持原字节。这个收紧值令名义机体坐标到紫侧墙内表面 `-2.501` 约有 0.301 m 几何距离；它并非实测机身净空保证。

复测**确定不合格，已按“只重试一次、失败即收尾”停止并回滚**。循环中正式记录了首轮红、紫、蓝 **3 局**，各局开场均有三只球，持续 GC 共 `86+85+97=268` 次、错误零。首轮蓝色在同一 UE PID 162457 下，18:33:06.374–08.203 UTC 检到 `3→2`，18:33:10.033–11.862 UTC 又检到 `2→1`，稳定快照仍为 1。真实帧显示第一次删球后蓝球仍在，之后蓝球消失，约 18:33:30 UTC 紫球仍在，故**先误击红球，再击破指定蓝球**。零误击与零同局双删两项硬门槛已经不可挽回，继续跑完九局不能使本次复测通过；为避免消耗共享仿真资源，完整记录这个反例后提前停试。**本次不是九局完成率样本，不能写成复测 9 局成功率。**

| 已登记试验 | 三球开场→稳定数 | 本局判读 | 软件触边 |
|---|---|---|---:|
| r1 红 | `3→2` | [红球近景](evidence/r1_red_key/20261018T182211_089338Z_0109.jpg)后[消失](evidence/r1_red_key/20261018T182213_096153Z_0111.jpg)，目标击破 | 0 |
| r1 紫 | `3→3` | 漏击；BT 成功不能替代物理击破 | 4 |
| r1 蓝 | `3→2→1` | **先红球误击，再蓝球击破；同局双删** | 2 |

蓝色同局的可复核图像时序：[蓝、紫同框](evidence/r1_blue_key/20261018T183302_618533Z_0104.jpg)；[第一次删球后蓝仍在](evidence/r1_blue_key/20261018T183307_899029Z_0109.jpg)；[蓝球贴近](evidence/r1_blue_key/20261018T183310_098270Z_0111.jpg)→[第二次删球后蓝消失](evidence/r1_blue_key/20261018T183311_098584Z_0112.jpg)；[之后紫球仍在](evidence/r1_blue_key/20261018T183330_218196Z_0130.jpg)。第一次被删的只能是同局剩余的红球；这项颜色结论没有跨 UE 重置沿用 Actor ID。对应删除 Actor ID 为 `...1420`、`...1417`，最后保留 `...1415`；[完整 GC 事件](evidence/r1_blue_gc_events.jsonl)、[前后/稳定场景快照](evidence/r1_blue_scene_snapshots.jsonl)与[相机时间索引](evidence/r1_blue_frame_index.jsonl)可逐秒重算。

## 原始证据、停止过程与回滚

- 远端批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_final_retry_ymin_20261019/`；[三局汇总](evidence/retry_gc_summary.csv)，MD5 `45f5c197c9c06ad1be48b6a0c94d7523`；[三局持续 GC/观察器/场景快照/变化时窗帧包](evidence/retry_evidence.tar.gz)，MD5 `2c8a99e082523c858912871a65fc7ddc`；[六次触边的前/中/后相机原帧及时间索引](evidence/retry_boundary_frames.tar.gz)，MD5 `9f25c9dca11f0b102652bd06f0736bc0`。[蓝色双删的扩展连续帧](evidence/r1_blue_double_frames.tar.gz)和[返航后帧](evidence/r1_blue_after_frames.tar.gz)保留了上表判断所用的全部局部画面。
- 发现蓝色双删时第二轮红色已经启动。先只 `SIGSTOP` 本人启动的循环 shell PID 153824，**没有打断正在进行的正式试验**。该红局完成、正式锁消失、PX4 `armed: False` 后才终止停住的编排器。因此 `trials.csv` 只有上述三条；第二轮红色原始正式目录 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261019T023738_red_A0/` 另行保留，[场景快照](evidence/r2_red_unindexed_scene_snapshots.jsonl)为 3→2，[84 次连续 GC 原始事件](evidence/r2_red_unindexed_gc_events.jsonl)只有一次 `3→2`。它没有被循环写入 `trials.csv`，故**不混入三局受控汇总或颜色击破率**。[提前停止说明](evidence/early_stop_reason.txt)也保留在批目录。
- 修改前线上 `llm_mission.launch` MD5 `5550c580a4822e773a331bcef11f0c47`，已备份 `/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch.bak_20261019T0218`；[单变量字节补丁](../../hit_balloon_v2/patches/patch_safety_ymin_wall_clearance.py)后 MD5 `7a8ed54ad3c69f8a700b2dfbdb045c98`、XML 校验通过、`catkin_make --pkg mission_pkg -j2` 成功，重启后 ROS 实读 `-2.2`。否决后又将这份失败版备份为 `.bak_20261019T0243_rejected`，用前述原版备份恢复并编译、重启；最终线上 MD5 回到 `5550c580a4822e773a331bcef11f0c47`，ROS 实读 `safety/y_min=-3.0`、PX4 未武装、三球完整。对应完整状态见[最终封存报告](../hit_balloon_part1_final/REPORT.md)。

本次只比较同一台服务器、A0 的首轮三色，且以一项不可逆硬失败提前终止。它证明收紧参数的这次实测部署**不能验收**，不证明 `-2.20` 长期必定误击，也不能从三局推断碰撞概率。最终采用首批表现较好的原 v4 组合，但其紫色贴墙风险仍须如实保留；本轮不再提出第二个变量或继续优化。
