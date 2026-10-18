# 第一部分最终封存：A-v4 / B-v3 / C 原入口组合（2026-10-19）

## 封存结论

**这是第一部分气球阶段最终封存的线上版本；按用户新五项标准仍未完全通过验收。** 它是本轮两种候选中实测较好的版本：原组合新九局中，三球开局 9/9、指定色击破 8/9、确认误击 0/9、同局双删 0/9；但紫色第二轮的软件触边时相机拍到墙占大半画面，按指定规则应计 **1/9 局疑似贴墙**，不能写成“墙碰撞证据 0/9”。唯一允许的单变量复测把 `safety/y_min` 收紧到 `-2.20`，首轮蓝色就先误击红球、再击破蓝球，`3→2→1`；该硬失败不可能在同批后续局中消除，因而提前停试并回滚。**没有第三个候选或第二次复测。**

| 对照 | 样本与物理结果 | 风险判定 | 结论 |
|---|---|---|---|
| 本次现有最佳 v4 全量新批，[1.8](../hit_balloon_part1_1.8/REPORT.md) | 9 局，红 3/3、紫 2/3、蓝 3/3 指定球击破；0 误击、0 双删 | 1/9 局触边画面疑似贴墙；另一紫色漏击局结束时有贴墙画面但未触发软件边界 | 四项满足，一项未满足；**不宣布通过** |
| 唯一单变量收紧 `y_min`，[1.9](../hit_balloon_part1_1.9/REPORT.md) | 首轮 3 局有效、GC 268 次零错；红目标击破，紫漏击，蓝先误击红球再击蓝球 | 蓝局双删且误击；紫 4 次、蓝 2 次软件触边 | 提前否决，不作九局率估计；已回滚 |

历史四批的 20 次触边帧另在[墙体调查回溯](../hit_balloon_part1_boundary_survey/REPORT.md)；其中数局也存在贴墙疑似。真实比赛对机身与墙的接触扣分；目前仅有第一视角帧、里程计和 UE 墙体包围盒，**没有碰撞冲量或机身接触的独立真值**。这里按用户要求把墙占画面大半计为疑似，不把软件边界次数直接冒充比赛扣分，也不把未拍到机身接触说成绝对安全。

## 线上实际部署与完整源码

2026-10-19 最后一次回滚后：`catkin_make --pkg mission_pkg -j2` 返回 0，仿真重启日志 `environment_started=1`，ROS 实读 `safety/y_min=-3.0`、`safety/y_max=3.0`，A/B/C 的 `approach_pos` 分别为 `4.3;1.0;0.7`、`4.3;-2.0;0.7`、`5.3;1.0;0.7`。`/mavros/state` 为 `connected: True, armed: False`，无正式试验锁；[最终只读场景快照](evidence/final_scene_snapshots.jsonl)为同一新 UE PID 200530 中 **3 只气球**。完整服务器 MD5 原件：[source_md5.txt](evidence/source_md5.txt)。

| 在线文件 | MD5 |
|---|---|
| `catkin_ws/src/mission_pkg/launch/llm_mission.launch` | `5550c580a4822e773a331bcef11f0c47` |
| `catkin_ws/src/mission_pkg/src/bt_ros.cpp` | `9b1cefe9dfa431418435f7f8f63a60ed` |
| `catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp` | `a63b57fa127a23cd8bb8e647f078ff21` |
| `catkin_ws/src/mission_pkg/src/nodes/action/goto.cpp` | `f557ace5bbf2ee7975b7335a738ffcf9` |
| `catkin_ws/src/mission_pkg/include/nodes/action/goto.h` | `ee765e08024ea28cb1b8d32104a272d3` |
| `catkin_ws/src/mission_pkg/src/mavros_cnt.cpp` | `edcd9397074f44c6028c8dca02902920` |
| `model/mission_once.py` | `fca24bf1142ca8cddfb9e8d39c387a43` |

[封存源码压缩包](source/final_deployment.tar.gz)按服务器相对路径保存以上七个文件的**原始字节**和 `manifest.json`（MD5/SHA256/字节数），压缩包 MD5 `6daf181d21e37bd9f59504924dc0db51`；服务器同字节副本为 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_final_freeze_20261019/final_deployment.tar.gz`。使用压缩包保存 launch 的 UTF-8+CRLF，避免 Git 或 Windows 文本管道改变换行后 MD5 不符。最终 flight 组合含早期已验证的控制/搜索补丁、1.4 红区视觉朝向、A-v4/B-v3、蓝球近距退出及其 G 阈值、蓝球 F 降速、E 返航前视、I 返航 via、J 冲刺后可见重对准；C 仍是原入口。**线上当前不是被否决的 `y_min=-2.20` 版。**

## 候选补丁清单与状态

“在用”指效果已包含在上表**实际源码字节**中，不表示单个补丁已单独证明长期性能。以下 A–M 是[1.6](../hit_balloon_part1_1.6/REPORT.md)的试验编号；N 是本轮唯一复测。已回滚/废弃脚本保留用于审计，**不要直接对当前 MD5 重新运行旧补丁**。

| 编号 | 脚本或版本 | 最终状态 |
|---|---|---|
| A | [B 入口 v1](../../hit_balloon_v2/patches/patch_purple_entry_route.py)、[v2](../../hit_balloon_v2/patches/patch_purple_entry_route_tuned.py) | 均被 C 的 B-v3 取代，不在用 |
| B | [蓝球近距丢帧后退出](../../hit_balloon_v2/patches/patch_blue_contact_loss_exit.py) | 在用；判据又被 G 收紧 |
| C | [B 入口 v3](../../hit_balloon_v2/patches/patch_purple_entry_boundary_margin.py) | **在用**：`4.3;-2.0;0.7` |
| D | [A 入口 v1](../../hit_balloon_v2/patches/patch_red_entry_avoid_blue.py)、[v2](../../hit_balloon_v2/patches/patch_red_entry_clearance_tuned.py)、[v3](../../hit_balloon_v2/patches/patch_red_entry_inner_clearance.py)、[v4](../../hit_balloon_v2/patches/patch_red_entry_interior_lane.py) | v1–v3 废弃；**v4 在用**：`4.3;1.0;0.7` |
| E | [返航 GoTo 前视](../../hit_balloon_v2/patches/patch_return_goto_lookahead.py) | 在用 |
| F | [蓝球冲刺速度 1.0](../../hit_balloon_v2/patches/patch_blue_sprint_speed.py) | 在用 |
| G | [蓝球近距退出阈值 0.30](../../hit_balloon_v2/patches/patch_blue_contact_loss_threshold.py) | 在用 |
| H | [C 入场向内](../../hit_balloon_v2/patches/patch_blue_entry_interior_lane.py) | **已回滚、废弃**：独立蓝局曾 `3→0` |
| I | [蓝球返航 via](../../hit_balloon_v2/patches/patch_blue_return_via.py) | 在用 |
| J | [蓝球冲刺后目标仍可见则重对准](../../hit_balloon_v2/patches/patch_blue_visible_after_sprint.py) | 在用；独立 3 局未实际走到该新分支，效果未单独证实 |
| K | [B 入口再向内 0.5 m](../../hit_balloon_v2/patches/patch_purple_entry_extra_margin.py) | 已回滚、废弃：独立紫色有漏击和越界 |
| L | [紫球前进速度 0.6](../../hit_balloon_v2/patches/patch_purple_approach_speed.py) | 已回滚、废弃：独立紫色 2/3 击破 |
| M | [紫球冲刺速度 0.6](../../hit_balloon_v2/patches/patch_purple_sprint_speed.py) | 已回滚、废弃：仅两局有效，另局环境中断；未证实优于 v4 |
| N | [安全 y 下界收紧到 -2.20](../../hit_balloon_v2/patches/patch_safety_ymin_wall_clearance.py) | **已回滚、废弃**：同局红球误击＋蓝球击破 |

为避免遗漏同目录中**早于 A–N 的脚本**：当前源码仍含 [冲刺观测日志](../../hit_balloon_v2/patches/patch_sprint_observability.py)、[对齐死区](../../hit_balloon_v2/patches/patch_alignment_deadzone.py)、[冲刺居中门](../../hit_balloon_v2/patches/patch_sprint_center_gate.py)、[近距重对准](../../hit_balloon_v2/patches/patch_close_align_reacquire.py)、[红球朝向门](../../hit_balloon_v2/patches/patch_red_heading_guard.py)、[丢目标位置保持](../../hit_balloon_v2/patches/patch_search_position_hold.py)、[1.4 红区视觉朝向](../../hit_balloon_v2/patches/patch_red_entry_perception.py)。旧 [颜色 guard](../../hit_balloon_v2/patches/patch_mission_color_guard.py)的目的仍由当前 `mission_once.py` 承担，但该历史脚本不能套用到最终完整文件，应以封存字节及规则合规报告为准。

[红入场 yaw π](../../hit_balloon_v2/patches/patch_red_entry_yaw.py)、[红高位](../../hit_balloon_v2/patches/patch_red_staging_height.py)、[红末段下降](../../hit_balloon_v2/patches/patch_red_final_descent.py)已被 1.4/A-v4 后续版本取代；[临时 yaw 探针](../../hit_balloon_v2/patches/patch_yaw_probe.py)和[冲刺接触刹车](../../hit_balloon_v2/patches/patch_sprint_abort_on_contact.py)已回滚。[紫球搜索锚点](../../hit_balloon_v2/patches/patch_purple_search_anchor_interior.py)、[紫球软 y 留距](../../hit_balloon_v2/patches/patch_purple_soft_y_clearance.py)、[紫球冲刺时长](../../hit_balloon_v2/patches/patch_purple_sprint_time.py)是**仅写过脚本、未部署/未做正式试验**的弃用设想；不得与已验证版本混称。`restore_mission_color_guard.sh` 是历史回滚脚本，不是新的候选。

## 证据、恢复方法与适用范围

- 世界坐标原始时间序列、墙/地板盒和四批 20 次触边回溯：[调查报告](../hit_balloon_part1_boundary_survey/REPORT.md)。三球确实沿各自车道移动；紫球中心 `y=-2.100`、墙内表面约 `-2.501`，旧软件下界 `-3.0` 并非“距墙很远”的安全裕量。
- 新全量九局：[1.8 汇总与原始 GC/真实帧](../hit_balloon_part1_1.8/REPORT.md)，远端 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_final_acceptance_20261019/`；唯一单变量复测：[1.9 局部证据及停止原因](../hit_balloon_part1_1.9/REPORT.md)，远端 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_final_retry_ymin_20261019/`。原始正式 trial 目录均在各报告 CSV，保留未删。
- 本轮回滚已执行：把失败 launch MD5 `7a8ed54ad3c69f8a700b2dfbdb045c98` 另存为 `llm_mission.launch.bak_20261019T0243_rejected`，再从先前原版备份 `llm_mission.launch.bak_20261019T0218` 恢复。若以后需**重部署本封存版**，先确认没有正式锁、PX4 `armed: False`，给即将覆盖的在线文件逐一做日期备份与 MD5，然后从服务器封存压缩包在 `/home/ubuntu/` 解出对应路径；对 C++ 执行 `touch`、`catkin_make --pkg mission_pkg -j2` 并在机体未武装时重启仿真，最后复核上表七个 MD5、ROS 参数和三球开局。可以先用 `tar -tzf /home/ubuntu/tcei_baseline_tools/results/hit_balloon_final_freeze_20261019/final_deployment.tar.gz` 预览七条路径。**不要直接覆盖整份 launch 的其他项目新改动**；如之后已有队友修改，先审阅差异再按字节定点恢复。原始正式证据不属于回滚对象。

本封存结果只对这台 `ChallengeMap`、A0、每次真实三球开局、连续 GC 与约 1 Hz 相机采样有效。首批目标击破 8/9 不等于比赛当天稳定拿到 25 分；紫色 1/3 漏击，另有贴墙疑似，官方整局观察器 `mission_success` 仅 2/9。因用户明确要求一轮单变量复测后无论结果如实结束，**此处停止气球相关代码改动**；若未来取得新的明确 bug 证据，再另立任务。
