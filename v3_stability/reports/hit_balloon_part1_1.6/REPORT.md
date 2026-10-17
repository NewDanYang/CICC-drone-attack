# 1.6 气球误击修复部署与独立试验（2026-10-18）

## 起点与同口径对照

[1.5 根因报告](../hit_balloon_part1_1.5_root_cause/REPORT.md)先于本轮源码修改完成。[红紫蓝各一局持续 GC 对照](../hit_balloon_part1_1.5_root_cause/gc_control_summary.csv)的 Actor 结局分别为 `3→2、3→1、3→1`，连续采样 85、79、90 次，三局均 0 错误；越界为 `0、2、0` 次。当前 1.4 只改变红区；紫/蓝的 `bt_ros` 分支、launch 坐标和 `visual_servo.cpp` 与 1.1 基线相同，因此紫/蓝两局是在同一飞行代码、同一 GC 口径下的旧版对照。红区对照是 1.4 现状。

所有批次均使用 `run_with_scene_snapshots.sh` 的 `TCEI_GC_CONTINUOUS=1`：正式任务前启动 [`gc_timing_probe.py --mode continuous --interval 1.5`](../../hit_balloon_v2/tools/gc_timing_probe.py)，任务后延续 3 秒，再作 `after/late/settled` 快照。GC 可能改变时序，故本报告只横比同策略批次。每局先验 UE 三球，不足即在解除武装后重置；原始 `events.jsonl`、真实帧、`observer.out` 均在下文列出的远端正式目录内。

## 单变量 A：B 区入场位置 v1

仅定点修改线上 `llm_mission.launch` 的 B 区 `approach_pos` 和 `goal`，共同表示一个入场位置，从 `5.3;-2.0;0.7` 到 `3.5;-2.4;0.7`；A/C 坐标、B yaw、C++ 代码不变。[MD5 锁定的补丁脚本](../../hit_balloon_v2/patches/patch_purple_entry_route.py)要求原 MD5 `cff7ff38bf7ac9ef98ee890a1c8644e8`，新 MD5 `7b730887e836ba2861e00681a3a0f17b`；[实部署 diff](deployed_B_entry.diff)与服务器备份 `/home/ubuntu/hit_balloon_purple_entry_backup_20261018T0052/` 保存原字节、MD5 和 `restore.sh`。首次部署尝试因脚本没有匹配 launch 中 `goal` 行的九个空格而**安全退出且 MD5 未变**；改正锚点后才写入。XML 解析通过；`catkin_make --pkg mission_pkg -j2` 返回 0，因没有 C++ 改动未重建对象；重启后 ROS 参数实读为 `3.5;-2.4;0.7`。

独立紫球三局 [逐局 CSV](B_v1_purple_summary.csv)，原始批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_B_purple_20261018/`；三局正式目录在 CSV 中。每局三球开局，GC 采样错误 0。Actor 结局 `3→3、3→2、3→3`，越界 `0、0、1`；**0/3 额外删球，但仅 1/3 有删球，目标击破不稳定，故 v1 失败**。第一局的真实帧在 50 秒跟踪窗口将结束时仍显示紫球，不能以“未误击”掩盖“未击中”。该批只适用于紫色、A0、此接近点，不能推断三色成功率。

## 单变量 A 的调优 v2

保持 A/C 与全部 C++ 不变，只把 B 区同一入场位置从 `3.5;-2.4;0.7` 调至 `4.3;-2.4;0.7`。[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_purple_entry_route_tuned.py)要求 v1 MD5 `7b730887e836ba2861e00681a3a0f17b`，写入后 MD5 `fbc7556d8e0506563152e8eac9ec69f5`；[diff](deployed_B_entry_tuned.diff)、服务器备份 `/home/ubuntu/hit_balloon_purple_entry_tuned_backup_20261018T0113/` 可审计。XML 解析通过、环境重启后 ROS 参数实读 `4.3;-2.4;0.7`。独立三局批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_B_tuned_purple_20261018/`。

[逐局 CSV](B_v2_purple_summary.csv)记录三局均 `3→2`，连续 GC 采样 `88、72、100` 次，错误 0；越界 `0、1、0`，没有同局第二次删球。三局真实任务的 BT 均报告成功，但第 1、3 局 `mission_success=false`、runner 返回 1，因此这里仅能确认 **3/3 删除恰好一球**，不能把它写成整局任务成功率。此批仅证明 B-v2 在紫色、A0、连续 GC 下优于 v1 的 `1/3` 删球；一局越界已用掉最终九局的全部边界预算。

## 单变量 B：蓝球近距丢帧后退出搜索

同口径旧版蓝球对照在 `3→2` 后的 50 秒搜索窗口又变成 `2→1`。蓝球近景与随后目标丢失、红球近景及搜索期间第二次删球的时序见 [根因报告](../hit_balloon_part1_1.5_root_cause/REPORT.md)及其中真实帧。B-v2 紫球三局完成后，才独立部署 [蓝球近距丢帧补丁](../../hit_balloon_v2/patches/patch_blue_contact_loss_exit.py)：只在目标色为蓝、已有目标、最大面积达到接近阈值的 75%、最后有效面积达到阈值的 50%、且丢帧仅超过超时阈值 0.25 秒内，悬停并返回视觉舵机成功，结束原有 50 秒搜索。其余颜色与正常追踪路径仍走原逻辑。[线上实际 diff](deployed_blue_contact_loss.diff)为唯一 C++ 改动。

补丁严格要求线上 `visual_servo.cpp` 原 MD5 `e440050ecfc06657d5ac4b472411fef6`，部署后为 `5a9bb56d2fef2aa3127c3a61bb153656`。服务器原文件、diff、MD5 和带 `touch`、重新编译的 `restore.sh` 保存在 `/home/ubuntu/hit_balloon_blue_contact_backup_20261018T0133/`。[编译日志](blue_build.log)显示 `visual_servo.cpp.o` 实际重建及 `visual_servo.so` 重新链接，`catkin_make --pkg mission_pkg -j2` 退出码 0。B 路线保持 v2 MD5 `fbc7556d8e0506563152e8eac9ec69f5`。

与 B-v2 合并后的第一批九局见 [1.7 验收报告](../hit_balloon_part1_1.7/REPORT.md)及[逐局 CSV](../hit_balloon_part1_1.7/batch1_gc_summary.csv)。蓝球三局均 `3→2`、0 边界、0 GC 错误；第一局此判据于 17:50:17.093 UTC 实际触发，真实帧可同时证明红、紫球后来仍在；第二局正常冲刺，无须进入该分支。**这只证明三局蓝球表现，不能抵消同批红球误击和紫球越界，因此合并候选未过全量验收。**

## 第一批失败后的单变量 C：B 区边界余量 v3

第一批九局紫球的 `3→2` 为 3/3，但各触发 `1、3、2` 次边界；六次安全恢复日志均在 `y≈-3.0 m`、现有下界 `safety/y_min=-3.0 m` 附近。第二轮最早越界比删球早约 19 秒，不能归因于击破后搜索。红球第三局另在 A/C 共用入场点先删蓝球，属于另一故障，**未混入本次 B 修改**。

[B 区边界余量补丁](../../hit_balloon_v2/patches/patch_purple_entry_boundary_margin.py)仅把 B 的 `approach_pos` 和 `goal` 这一个入场位置从 `4.3;-2.4;0.7` 改为 `4.3;-2.0;0.7`；A/C、全部 C++、安全边界原值不变。它要求线上 B-v2 launch MD5 `fbc7556d8e0506563152e8eac9ec69f5`，部署后 MD5 `4d515907e69df212bfd48ec71489847b`；本地先用线上字节副本运行脚本，MD5 和 XML 解析均通过。正式部署前核对上一批 `exit_code=0`、无锁、机体未武装；备份 `/home/ubuntu/hit_balloon_purple_boundary_backup_20261018T0230/` 包含原文件、diff、MD5 和 `restore.sh`，[实际部署 diff](deployed_B_boundary_margin.diff)。重启后环境 `environment_started=1`，ROS `/balloon_zone_B/approach_pos=4.3;-2.0;0.7`。

独立紫球三局目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_B_margin_purple_20261018/`，循环 `exit_code=0`；[逐局 CSV](B_v3_purple_summary.csv)与[GC 及真实帧原始证据包](B_v3_purple_evidence.tar.gz)可重查。三局均三球开局、稳定 `3→2`，连续 GC `91、108、85` 次、错误 0，边界 **0、0、0**。第三局[紫球近景](evidence_Bv3_r3/purple_near.jpg)与[下一帧消失](evidence_Bv3_r3/after.jpg)支持目标被击；其余两局也有同类近景和消失帧，均在证据包内。与 B-v2 第一批九局中的紫球三局（`3→2` 均成立但边界 `1、3、2`）相比，B-v3 在单色三局中保持删一球且边界从 3/3 局降到 0/3 局。该小样本不证明全色验收通过，仍需 A 区独立修复及新九局。

## 单变量 D：A 区避开蓝球入场点

第一批九局红球第三局在 `VisualServo` A/C 共用入场点附近先删蓝球：第一次 GC `3→2` 时机体约 `(5.35,0.91,0.41)`，红球仍在真实帧，随后红球冲刺、GC `2→1`，返航帧还看得见紫球。详见 [1.7 首批证据](../hit_balloon_part1_1.7/REPORT.md)。这一局证据指向**A 入场位置附近的非目标碰撞**，与 B 区边界问题分开。B-v3 紫球三局和证据封存后才部署本项。

[A 区避蓝球补丁](../../hit_balloon_v2/patches/patch_red_entry_avoid_blue.py)只把 A 的 `approach_pos` 从 `5.3;1.0;0.7` 改为 `5.3;1.8;0.7`，`goal` 从 `5.3;1.0;1.0` 改为 `5.3;1.8;1.0`；两项共同代表同一入场走廊，保留原高度差。B/C、C++、安全边界均不变。补丁要求线上 B-v3 launch MD5 `4d515907e69df212bfd48ec71489847b`，部署后 `f1260a19358e2a28839afd404a3c4393`；先用线上字节副本试跑并解析 XML，正式部署前再次确认 B-v3 批 `exit_code=0`、无正式锁、机体未武装。[实际 diff](deployed_A_avoid_blue.diff)、服务器备份 `/home/ubuntu/hit_balloon_red_avoid_blue_backup_20261018T0252/` 可核对，内有原字节、MD5 和带 `touch` 的 `restore.sh`。

重启后的独立红球三局见 [逐局 CSV](A_v1_red_summary.csv)、[连续 GC 与真实帧证据包](A_v1_red_evidence.tar.gz)，远端原始目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_A_avoid_blue_red_20261018/`。三局开局均 3 Actor，GC 采样 `78、79、178` 次、错误 0，结局虽都是 `3→2`，但第 3 局**任务超时、BT 无成功、视觉舵机未启动**。规划器在 `(5.3,1.8,0.7)` 目标点反复报告 `terminal point of the current trajectory is in obstacle`；`checkArrival` 长期停在约 `(4.75–5.03,1.4–1.56,0.6–0.8)`，距离目标约 0.4–0.65 m，大于 0.15 m 容差。该局一次删球发生在停滞期间；变化时窗相机只拍到墙面，无法确定被删颜色，**不能将 `3→2` 当作红球击破**。第 1、2 局 BT 与观察器均成功、画面有红球近景及消失，边界分别 0、1 次；第 2 局边界发生在红球冲刺后，触发位置约 `x=-1.01 m`。故 A-v1 作为稳定修复失败。

## 单变量 D 的调优 v2

保持 B-v3、蓝球 C++ 和安全边界不变，仅将 A 同一入场走廊的 y 从 `1.8` 调到 `2.1`，保留 x=`5.3` 和两项原高度。目标是拉开与第 3 局停滞位置以及移动球车路径的距离；**这是待测假说，不是已证实的障碍物净空**。[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_red_entry_clearance_tuned.py)要求 A-v1/B-v3 launch MD5 `f1260a19358e2a28839afd404a3c4393`，写入后 `bb6b4821b4a0d6293738c369462c5827`；先用线上字节副本 dry-run，XML 解析、MD5 均通过。部署前 A-v1 批退出码 0、无正式锁、机体未武装。[线上 diff](deployed_A_clearance_tuned.diff)、备份 `/home/ubuntu/hit_balloon_red_clearance_backup_20261018T0330/` 保存原字节、MD5 和回滚脚本。

独立红球三局见 [逐局 CSV](A_v2_red_summary.csv)、[原始 GC 与真实帧证据包](A_v2_red_evidence.tar.gz)，远端原始目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_A_clearance_red_20261018/`。均三球开局，连续 GC `97、89、175` 次、0 错误；结局分别 `3→2、3→2、3→3`，边界 `1、0、0`。第一局后续帧能看到紫、蓝都仍在，故唯一删球为红；边界在删球后约 0.7 秒触发于 `x≈-1.00 m`。第二局 BT 和观察器成功。第三局再次在 A 目标 `(5.3,2.1,0.7)` 遇到规划器“终点在障碍物内”，`checkArrival` 到约 `(4.27,2.18,0.86)` 仍距目标 1.05 m，视觉舵机未启动，正式任务 300 秒超时；三只球始终都在。**A-v2 失败**，证明沿 y 向外挪 0.3 m 没解决终点可达性。

## 单变量 D 的调优 v3

根据 A-v2 第三局已到达而未触发边界的内侧位置，只将 A 入场的 x 从 `5.3` 收回到 `4.3`，y=`2.1`、两项高度、B/C 与 C++ 保持不变；这个坐标仍须用真局验证可达及正确击球。[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_red_entry_inner_clearance.py)要求 A-v2/B-v3 launch MD5 `bb6b4821b4a0d6293738c369462c5827`，部署后 `effb5fe21b38f4a773acc37663172f0a`。先用线上 A-v2 字节副本 dry-run，XML 和 MD5 均通过；实际部署前 A-v2 批退出码 0、无正式锁、机体未武装。[线上 diff](deployed_A_inner_clearance.diff)、备份 `/home/ubuntu/hit_balloon_red_inner_backup_20261018T0345/` 可复核。

首局正式目录 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T034644_red_A0/`，其 [单局 manifest](A_v3_red_single_trials.csv)、[GC 汇总](A_v3_red_single_summary.csv)和[原始证据包](A_v3_red_single_evidence.tar.gz)另存。三球开局，178 次连续 GC 均成功、一直 `3→3`，边界 0；机体停在约 `(3.76,2.09,0.91)`、离 A 目标约 0.58 m，规划器持续报告终点在障碍物内，任务 300 秒超时。由于这一局已经不符合九局零失败目标，首局完整结案后终止后续 A-v3 循环，不将 `exit_code` 的进程终止值视为三局完成。循环终止使 PX4 仍武装在 OFFBOARD；按原循环的收尾方法调用 `/mavros/cmd/land` 返回 `success: True`，再确认 `armed: False` 和无正式锁，才进入下一次部署。**只凭这一局不能估计 A-v3 成功率，但足以判定这批不可能达成 9/9。**

## 单变量 D 的调优 v4

前三版 A 的 `y=1.8/2.1` 都在若干局遇到目标不可达；原 1.4 的 `y=1.0` 可达但 `x≈5.3` 曾与蓝球共用入场区域并误击。因此仅将 A 的 y 从 `2.1` 收回 `1.0`，保留内侧 x=`4.3` 以与首批误击点 `(5.35,0.91)` 保持约 1 m 水平距离，B/C、C++ 和安全边界不变。这是待测的几何折中，不能由坐标差直接断言零误击。[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_red_entry_interior_lane.py)要求 A-v3/B-v3 launch MD5 `effb5fe21b38f4a773acc37663172f0a`，写入后 `5550c580a4822e773a331bcef11f0c47`；线上字节副本 dry-run、XML 解析通过。[实际 diff](deployed_A_interior_lane.diff)和备份 `/home/ubuntu/hit_balloon_red_interior_backup_20261018T0400/` 保存原件及回滚脚本。

截至服务器连接中断前，独立红球前两局正式目录为 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T035925_red_A0/`、`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T040532_red_A0/`：均三球开局、连续 GC 分别 88/84 次成功、只发生一次 `3→2`、边界 0。[首局 GC 与真实帧证据包](A_v4_r1_evidence.tar.gz)及[红球近景](evidence_Av4_r1/red_near.jpg)、[破裂光点](evidence_Av4_r1/red_pop.jpg)、[下一帧红球消失](evidence_Av4_r1/red_gone.jpg)处于同一时窗，目标色有直接画面证据。第二局最终 `settled=2`、BT 成功；颜色还需核验原始帧。两局观察器的 `hit_balloon_status` 均未记录，不能把 `mission_success=false` 等同于物理删球失败。第三局在 3 Actor 场景开始后，SSH 端口 `30316` 拒绝连接；任务结局和服务器状态待恢复后核对，**A-v4 仍未完成三局独立结论，也未进入新的九局验收**。

## 回滚

先确认没有正式试验运行且机体已解除武装，再分别执行：

```bash
bash /home/ubuntu/hit_balloon_red_interior_backup_20261018T0400/restore.sh
bash /home/ubuntu/hit_balloon_red_inner_backup_20261018T0345/restore.sh
bash /home/ubuntu/hit_balloon_red_clearance_backup_20261018T0330/restore.sh
bash /home/ubuntu/hit_balloon_red_avoid_blue_backup_20261018T0252/restore.sh
bash /home/ubuntu/hit_balloon_blue_contact_backup_20261018T0133/restore.sh
bash /home/ubuntu/hit_balloon_purple_boundary_backup_20261018T0230/restore.sh
bash /home/ubuntu/hit_balloon_purple_entry_tuned_backup_20261018T0113/restore.sh
bash /home/ubuntu/hit_balloon_purple_entry_backup_20261018T0052/restore.sh
```

先按逆序撤四版 A 走廊，再恢复原 C++（此脚本 `touch` 并重新编译），最后三个脚本按逆序恢复 B 区 launch 到 1.4 版本。随后重启仿真，核对 C++ MD5 `e440050ecfc06657d5ac4b472411fef6` 和 launch MD5 `cff7ff38bf7ac9ef98ee890a1c8644e8`。备份和全部原始试验目录保留。
