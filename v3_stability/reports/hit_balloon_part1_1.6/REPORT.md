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

断线前两局的[逐局 CSV](A_v4_red_before_disconnect_summary.csv)及[原始证据包](A_v4_red_before_disconnect_evidence.tar.gz)对应正式目录 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T035925_red_A0/`、`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261018T040532_red_A0/`。两局均三球开局、连续 GC 分别 88/84 次成功、仅一次 `3→2`、边界 0。[首局红球近景](evidence_Av4_r1/red_near.jpg)、[破裂光点](evidence_Av4_r1/red_pop.jpg)、[下一帧消失](evidence_Av4_r1/red_gone.jpg)以及[第二局红球近景](evidence_Av4_r2/20261017T200723_254036Z_0107.jpg)、[下一帧消失](evidence_Av4_r2/20261017T200724_374043Z_0108.jpg)与各自唯一 GC 删球同窗。两局观察器均未单独记录 `hit_balloon_status`，故 `mission_success=false` 与实际红球击破须分别报告。第三局在三球开局后因服务器连接中断未完成，**不能计入样本**；恢复时确认该局原仿真与正式进程均已退出，清理死进程锁后重启仿真。

保持线上 launch MD5 `5550c580a4822e773a331bcef11f0c47`、C++ MD5 `5a9bb56d2fef2aa3127c3a61bb153656` 不变，再跑独立红球三局。远端批目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_A_interior_red_recovery_20261018/`，循环 `exit_code=0`；[逐局 CSV](A_v4_red_recovery_summary.csv)、[连续 GC、真实帧证据包](A_v4_red_recovery_evidence.tar.gz)。三局都三球开局，GC 采样 `77、96、71`（合计 244）次，错误 0，均仅一次 `3→2`，边界触发 `0、0、1`。每局真实帧都显示红球接近并在 GC 删球窗口内消失：例如[第一局近景](evidence_Av4_recovery_r1/20261018T022127_629292Z_0107.jpg)与[破裂光点](evidence_Av4_recovery_r1/20261018T022128_630228Z_0108.jpg)、[第二局近景](evidence_Av4_recovery_r2/20261018T022716_427518Z_0109.jpg)与[破裂光点](evidence_Av4_recovery_r2/20261018T022717_547869Z_0110.jpg)、[第三局近景](evidence_Av4_recovery_r3/20261018T023332_652900Z_0102.jpg)与[下一帧消失](evidence_Av4_recovery_r3/20261018T023333_652927Z_0103.jpg)。第三局的一次边界触发仍是反例，A-v4 不能据此宣称达到整批九局的边界预算；须在 1.7 重新计量。恢复批正式任务成功记录为 `true、false、true`，中间一局 BT 成功、物理删红球，但观察器未记录独立气球阶段成功；这不是三局完整任务 3/3 成功。与同口径旧版红球对照 n=1 相比，A-v4 完成的五局均正确删红球且无同局第二次删球，仍只能表述为 A0 和此批场景下的观察结果。

## 单变量 E：降落返航 GoTo 前视设定点

[第二批九局验收](../hit_balloon_part1_1.7/REPORT.md#第二批b-v3a-v4蓝球近距退出)在蓝球第 1、2 局的唯一边界触发分别为 `x=-1.01`、`-1.09 m`，两次均在 GC 已记录蓝球被删之后，`GoTo` 从约 `(5.5,0.8,0.3)` 直接指令原点返航时发生。第三局蓝球没有触发；紫球第 1 局另有 y 边界反例，不能归入返航过冲。A-v4/B-v3、蓝球视觉舵机与安全边界保持不变，本项只给 **`land` 阶段生成的返航 GoTo** 设置 `setpoint_lookahead=0.6 m`：每次最多向当前位置前方 0.6 m 发布位置设定点，仍以原点作为真正到达判据；其他 GoTo 节点默认 0，保持原行为。数值 0.6 m 是待真局验证的控制限幅，不声称仅凭代码就能消除过冲。

[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_return_goto_lookahead.py)在线上原文件 `goto.cpp` `f0710df499635efdc01dc8bd071ff018`、`goto.h` `835ee5c7cf6ea67de6f12e656285597b`、`bt_ros.cpp` `0ce0f6ec147d516d20e1a89d612792a6` 上先本地 dry-run，通过后才部署。新 MD5 分别为 `f557ace5bbf2ee7975b7335a738ffcf9`、`ee765e08024ea28cb1b8d32104a272d3`、`488e0fa3894feb527a8b1e921770e9c4`；[实际部署 diff](deployed_return_goto.diff)及服务器备份 `/home/ubuntu/hit_balloon_return_goto_backup_20261018T113556/` 含三份原文件、MD5、diff 和 `restore.sh`。部署前确认第二批 `exit_code=0`、无正式锁、PX4 `armed: False`。[编译日志](return_goto_build.log)显示 `goto.cpp.o`、`bt_ros.cpp.o` 重建，`goto.so` 重新链接且 `catkin_make --pkg mission_pkg -j2` 退出码 0；随后重启仿真加载新库。蓝球第一局的原始日志生成树 XML 只在降落返航节点出现 `setpoint_lookahead="0.6"`。

独立蓝球三局远端 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_return_goto_blue_20261018/`、循环 `exit_code=0`；[逐局 CSV](return_goto_blue_summary.csv)与[GC/真实帧证据包](return_goto_blue_evidence.tar.gz)记录每局三球开局、连续 GC `71、67、69`（合计 207）次、错误 0、均只有一次 `3→2`，边界为 **0、1、0**。第二局[蓝球近景](evidence_return_blue_r2/20261018T034749_348914Z_0095.jpg)、[破裂光点](evidence_return_blue_r2/20261018T034750_428342Z_0096.jpg)且紫球仍在同一近景帧，明确排除仅靠跨 UE Actor ID 判断颜色；该局唯一边界在蓝球冲刺约 1.1 秒处，机体 `y=-3.13`，**发生在返航 GoTo 启动之前**。本项没有消除蓝球全部越界，但三局中没有再出现 x 下界过冲。

[返航设定点与里程计距离对照](return_setpoint_control_vs_patch.jsonl)由[只读分析脚本](../../hit_balloon_v2/tools/return_setpoint_metrics.py)逐帧配对计算，最大时间错位 ≤0.032 秒。第二批未改返航的两局蓝球最大距离 `5.595、5.931 m`，限距后的三局为 `0.788、1.025、0.831 m`；设置值 0.6 m 与测得的实际最大距离不同，因飞行中的反馈/指令时间差与机体运动，不能把参数误写成硬边界。该小样本支持返航命令跨度显著减小，**不证明边界总数达标**。蓝球三局 BT 均成功，观察器 `mission_success=true` 为 2/3；剩余一局独立气球阶段事件未观察到。下一步把蓝球冲刺越过 y 下界作为新的单变量处理，再全量验收。

## 单变量 F：蓝球冲刺速度

返航限距的蓝球独立三局中，唯一 y 下界触发发生在蓝球冲刺约 1.1 秒处，而非返航。保持 A-v4/B-v3、返航 GoTo、蓝球近距退出与安全边界不变，[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_blue_sprint_speed.py)仅把生成行为树中的蓝球冲刺速度默认值从 1.5 降至 1.0 m/s；红/紫仍为 1.5 m/s。部署前 `bt_ros.cpp` MD5 `488e0fa3894feb527a8b1e921770e9c4`，部署后 `6ba77aa30eb4c42588d064820bcf852d`；服务器备份 `/home/ubuntu/hit_balloon_blue_sprint_speed_backup_20261018T115816/` 保存原文件与 `restore.sh`。[实际 diff](deployed_blue_sprint_speed.diff)、[编译日志](blue_sprint_speed_build.log)可复查；重编和重启后才开始试验。

独立蓝球三局远端 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_blue_sprint_speed_blue_20261018/`、循环 `exit_code=0`；[逐局 CSV](blue_sprint_speed_summary.csv)与[原始证据包](blue_sprint_speed_evidence.tar.gz)记录三球开局，连续 GC 采样 `64、72、98` 次、错误 0，Actor 结局 **`3→2、3→3、3→2`**，边界均为 0。第 2 局[真实近景帧](evidence_blue_speed_miss/20261018T040843_561706Z_0106.jpg)中蓝球仍完整，稍后相机掠过未破的[蓝球边缘](evidence_blue_speed_miss/20261018T040845_641824Z_0108.jpg)；完整时段[帧包](blue_speed_miss_frames.tar.gz)与 GC `3→3` 一致。该局尚未进入冲刺，视觉舵机就以 `BLUE_NEAR_CONTACT_LOSS_COMPLETE area=0.2673 max_area=0.2763 lost_s=1.003` 返回成功，所以这次漏击由旧近距退出条件误判引起，不能归咎于新冲刺速度。**冲刺速度的三局零边界观察不能证明候选成功，因为目标仅击破 2/3。**

## 单变量 G：收紧蓝球近距丢失后的完成判据

在上述漏击局后，比较此前真正击破且进入近距退出分支的四个蓝球局，其记录面积为 `0.3004、0.5306、0.4475、0.4156`；漏击局历史最大面积只有 `0.2763`。这些数来自真实正式试验日志，样本很小，仅用于选择待测阈值。[MD5 锁定补丁](../../hit_balloon_v2/patches/patch_blue_contact_loss_threshold.py)只将蓝球近距退出所需的历史最大面积比改为 `>=0.30`，其余丢帧时长、最后有效面积、颜色条件、冲刺速度和返航均保持不变。线上原 `visual_servo.cpp` MD5 `5a9bb56d2fef2aa3127c3a61bb153656`，新 MD5 `ae8e6172e4ddbfc851bcfdf080dc2aec`；[实际 diff](deployed_blue_contact_threshold.diff)、[编译日志](blue_contact_threshold_build.log)及备份 `/home/ubuntu/hit_balloon_blue_contact_threshold_backup_20261018T1230/` 保存审计和回滚证据。编译退出码 0，重启仿真后试验。

独立蓝球三局远端 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_contact_threshold_blue_20261018/`，循环 `exit_code=0`；[逐局 CSV](contact_threshold_blue_summary.csv)、[连续 GC 与真实帧证据包](contact_threshold_blue_evidence.tar.gz)均保留。每局三球开局，GC `70、77、70` 次，合计 217 次无错误，结局均 **`3→2`**，边界均为 0，无同局第二次删球。三局 `BLUE_NEAR_CONTACT_LOSS_COMPLETE` 面积分别为 `0.6242、0.3845、0.3320`。[第一局蓝球近景](evidence_contact_threshold_blue_r1/20261018T044353_426375Z_0103.jpg)、[第二局蓝球近景](evidence_contact_threshold_blue_r2/20261018T044938_075829Z_0113.jpg)与[消失后紫球仍在](evidence_contact_threshold_blue_r2/20261018T044939_196134Z_0114.jpg)、[第三局蓝球近景](evidence_contact_threshold_blue_r3/blue_near.jpg)与[下一帧消失](evidence_contact_threshold_blue_r3/blue_gone.jpg)和各局唯一 GC 删球同窗，支持三局正确击破蓝球。与旧阈值、相同蓝球冲刺速度的独立三局 `2/3` 正确击破相比，本批为 `3/3`；不能由此估计长期漏击概率。三局 BT 均成功但观察器 `mission_success=false`，独立气球阶段事件未被观察到，不等同于正式计分确认。仍需三色九局组合验收。

## 单变量 H：C 区蓝球入场向内移动

[第三批九局](../hit_balloon_part1_1.7/REPORT.md#第三批返航限距蓝球降速及收紧近距退出)的第一轮蓝球从 C 入场点 `5.3;1.0;0.7` 接近后，在 x 已达 `5.907`、蓝球滑到画面右缘时结束冲刺，随后机体到 `x=6.01` 触发上界，三球未减；第三轮蓝球虽然击破目标，返航却在 `(0.56,0.75,0.36)` 附近多删红球。两局都是同口径连续 GC 和真实帧确认的反例，但不保证一个坐标修改能同时解决返航问题。

先只改 C 的一组入场位置：`approach_pos`、`goal` 从 `5.3;1.0;0.7` 同时移到 `4.3;1.0;0.7`，C yaw、A/B、全部 C++、返航路线与安全边界保持不变。[MD5 锁定脚本](../../hit_balloon_v2/patches/patch_blue_entry_interior_lane.py)以线上原字节 MD5 `5550c580a4822e773a331bcef11f0c47` 为前置条件；本地对服务器字节副本 dry-run 后 MD5 `d95b449a8477b6077dd9bcbcc6a69048` 且 XML 可解析。正式部署前第三批循环退出码 0、无正式锁、PX4 `armed: False`。[实际 diff](deployed_C_interior_lane.diff)和备份 `/home/ubuntu/hit_balloon_blue_entry_interior_backup_20261018T1400/` 保存原文件、MD5 与 `restore.sh`。重启日志出现 `environment_started=1`，ROS 实读 `/balloon_zone_C/approach_pos=4.3;1.0;0.7`，然后启动独立蓝球三局 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_C_interior_blue_20261018/`。

该批首局运行期间，SSH 端口 30316 连续六次连接失败，随后 TCP 检测仍为拒绝连接。服务器恢复后核查发现原批 `exit_code=1`、仅一行 `valid=0`：正式任务虽有日志，但仿真进程在结束后场景快照前消失，连续 GC 和帧证据不完整；该局**不计入候选样本**。核查旧锁 PID 均已死亡、ROS master 不在线后清理残锁并启动环境，重新核实 `environment_started=1`、MAVROS `connected: True, armed: False`、线上 launch MD5 未变。

全新独立三局在 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_C_interior_blue_recover_20261018/` 完成，循环 `exit_code=0`；[逐局汇总](C_interior_recover_summary.csv)及[原始证据包](C_interior_recover_evidence.tar.gz)保存完整 `trials.csv`、连续 GC 事件、场景快照和变化时窗真实帧。三局开局均 3 Actor、`valid=1`，GC 分别 **`3→2、3→2→1→0、3→2`**，采样 `64、97、89` 次共 250 次，GC 错误 0；边界 `0、1、0` 次。第二局三个删球分别在 12:21:29、12:22:04、12:22:06 UTC；第一删时机体约在 `(4.49,1.02,0.36)` 的 C 入场附近，蓝球冲刺直到 12:22:01 才开始。第一次删球后一秒的[真实帧](evidence_C_recover_r2/20261018T122130_195758Z_0118.jpg)中蓝球、紫球都仍在，因此同局第一只被误击的是**红球**；先前的[两球同框](evidence_C_recover_r2/20261018T122127_114913Z_0115.jpg)可作对照。第二局又在蓝球冲刺末尾到 `y=-3.05` 触发一次下界，安全恢复期间两次额外删球，最终三球全部消失。第三局虽 `3→2` 且无边界，但正式 `runner_rc=1`、观察器整局未成功，不可视为全任务通过。

因此 C 向内移 1 m 的候选被明确否定：三局中 1 局误击并同局连删三球，1 局正式运行失败，不能进入九局验收。这里的颜色判断仅适用于第二局同一 UE 实例的前后帧，不跨场景复用 Actor ID。先回滚 C 的 `approach_pos/goal` 至 `5.3;1.0;0.7`，再独立处理蓝球返航误击；其余已部署代码保持原状。

## 单变量 I：蓝球返航绕开红球行进带

在 C 批次完整退出、无正式锁且 PX4 未武装后，运行 C 备份的 `restore.sh`；线上 launch MD5 回到 `5550c580a4822e773a331bcef11f0c47`，重启后 ROS 实读 C 入场 `5.3;1.0;0.7`。本项只改蓝球指令后、`land` 前的返航路线：在原点返航和降落之前插入内侧航点 `(1.0,-1.0,0.5)`，保留既有原点返航、其他颜色、视觉舵机及安全边界。[MD5 锁定脚本](../../hit_balloon_v2/patches/patch_blue_return_via.py)要求原 `bt_ros.cpp` MD5 `6ba77aa30eb4c42588d064820bcf852d`；对线上源码副本 dry-run 的 XML 构建片段 diff 与最终线上 [diff](deployed_blue_return_via.diff)一致，新 MD5 `9b1cefe9dfa431418435f7f8f63a60ed`。备份 `/home/ubuntu/hit_balloon_blue_return_via_backup_20261018T2040/` 含原文件、MD5、diff 和 `restore.sh`；[编译日志](blue_return_via_build.log)退出码 0，重启日志 `environment_started=1` 后开始独立蓝球三局 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_blue_return_via_20261018/`。

第一次生成的补丁误在 `buildXmlFromCommands` 使用仅在 `commandToXmlNode` 局部可见的 `getStr`，编译器报 `bt_ros.cpp:406 getStr was not declared`。失败源码**未重启、未跑试验**；先从 `/home/ubuntu/hit_balloon_blue_return_via_backup_20261018T2032/` 恢复原源码并单独重新编译成功，再从该干净 MD5 重新生成上述正式补丁。第一次备份的 `restore.sh` 因 `set -u` 与 ROS 环境脚本冲突，只完成复制；随后手工 `source /opt/ros/noetic/setup.bash && catkin_make --pkg mission_pkg -j2` 编译成功。正式备份脚本已在 source 前临时 `set +u`，可直接回滚并编译。

独立蓝球三局循环 `exit_code=0`，[逐局汇总](blue_return_via_summary.csv)和[原始证据包](blue_return_via_evidence.tar.gz)均已封存。三局均 3 Actor 开局、`valid=1`，连续 GC 采样 `79、70、68` 次，共 **217 次、0 错误**；结局为 **`3→3、3→2、3→2`**，没有同局第二次删球。第一局正式观察器 `mission_success=true`，但 GC 和稳定快照始终 3 只，属于物理漏击：冲刺结束日志 `pos=(5.551,1.137,0.393)`、`err_x=270 px`、`area=0.0636`、`target_fresh=1`，目标仍在画面右侧，旧代码却立刻 `SUCCESS` 并返航。第二局 `3→2`，但冲刺**前**追踪到 `(6.02,-1.50,0.30)` 触发一次 x 上界；第三局 `3→2`、边界 0，观察器因气球阶段事件未观测到而整局失败。与无航点的第三批蓝球三局（`3→3、3→2、3→2→1`）相比，本批未复现返航额外删红，但每组仅 3 局，不能宣称航点已消除误击；漏击和追踪越界仍是反例。先单独修正“明显可见仍判冲刺成功”，再测追踪边界。

## 单变量 J：蓝球冲刺后目标仍明显可见则重对准

[MD5 锁定脚本](../../hit_balloon_v2/patches/patch_blue_visible_after_sprint.py)只在蓝球冲刺达到固定 1.2 秒时新增判断：目标检测仍新鲜、画面面积比至少 0.03、水平偏差大于画面宽度的 20% 时，先悬停并返回 ALIGN，而不直接报告成功。其他颜色、追踪速度、冲刺时长、C 入场、返航航点、安全边界均不变。线上 `visual_servo.cpp` MD5 `ae8e6172e4ddbfc851bcfdf080dc2aec` → `a63b57fa127a23cd8bb8e647f078ff21`；[实际 diff](deployed_blue_visible_retry.diff)、[编译日志](blue_visible_retry_build.log)和备份 `/home/ubuntu/hit_balloon_blue_visible_retry_backup_20261018T2053/` 可复核。先对线上原字节 dry-run，再部署、编译退出码 0、重启 `environment_started=1` 后跑独立蓝球三局。

远端批次 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_blue_visible_retry_20261018/`，循环 `exit_code=0`；[逐局汇总](blue_visible_retry_summary.csv)与[原始证据包](blue_visible_retry_evidence.tar.gz)保存 3 局连续 GC 和真实帧。三局各 3 Actor 开局、有效，GC 分别 **`3→2、3→2、3→2`**，采样 `75、71、77` 次共 **223 次、0 错误**，边界 `0、0、0`，无同局第二次删球。三次变化时窗均有蓝球近景，例如[第 1 局蓝球近景](evidence_blue_visible_retry/r1_blue_near.jpg)、[第 2 局近景](evidence_blue_visible_retry/r2_blue_near.jpg)与[空车帧](evidence_blue_visible_retry/r2_empty_rover.jpg)、[第 3 局近景](evidence_blue_visible_retry/r3_blue_near.jpg)，GC 唯一删球与蓝球接触或丢失时段一致。三局均未出现 `BLUE_SPRINT_VISIBLE_RETRY`，所以这批只证明部署后未退化，**不能证明新分支救回了此前的漏击**。三局 BT 均成功；正式 `runner_rc=1` 和观察器 `mission_success=false` 均为独立气球阶段事件未观测到，需与物理击球分开。与上一批蓝球 `2/3` 删一球、`1/3` 边界相比，本批为 `3/3`、`0/3`，样本不足以断言长期成功率提升。

## 单变量 K：B 区紫球入场再向内 0.5 m

第三批九局的紫球第 3 轮在追踪时到 `y=-3.01`，B-v3 独立三局虽 0 边界但组合批 2/3 紫局越界。只把 B 的 `approach_pos`、`goal` 同一入场点从 `(4.3,-2.0,0.7)` 改为 `(4.3,-1.5,0.7)`；这是为追踪留空间的候选，不推定目标必可达。[字节级 MD5 锁定脚本](../../hit_balloon_v2/patches/patch_purple_entry_extra_margin.py)要求回滚 C 后 launch MD5 `5550c580a4822e773a331bcef11f0c47`，线上新 MD5 `54aa833a1d8dcf26f6564064329376e2`；先对线上原字节 dry-run、XML 解析通过，再在蓝球 J 批退出码 0、无正式锁、PX4 未武装后部署。[实际 diff](deployed_purple_extra_margin.diff)和备份 `/home/ubuntu/hit_balloon_purple_extra_margin_backup_20261018T2115/` 可回滚。重启与独立紫球三局结果另记于下，不把未测候选写成有效修复。

独立三局远端 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_purple_extra_margin_20261018/`，循环 `exit_code=0`，[逐局汇总](purple_extra_margin_summary.csv)和[原始证据包](purple_extra_margin_evidence.tar.gz)已封存。均三球开局、`valid=1`；连续 GC `91、94、83` 次，合计 **268 次、0 错误**；结局 **`3→2、3→3、3→2`**，边界 **`0、1、2`**。第 2 局在逆序穿框规划阶段 13:23:45 UTC 已到 `(3.00,-3.11,0.51)`，比视觉舵机启动早约 34 秒，不能归因于 B 入场；之后追踪到约 `(3.00,-2.47,0.00)`、目标丢失，正式结束仍 3 只。第 3 局视觉追踪在 13:29:23 UTC 到 `(4.99,-3.01,0.00)`，再于 13:29:48 UTC 到 `(3.87,-3.05,0.00)`，两次触发 y 下界；GC 仅一次 `3→2`，不能用删一球掩盖越界。此候选既有 **1/3 漏击**又有 **2/3 局越界**，明确失败；B 入口移至 `-1.5` 并不能限制后续视觉舵机向外追踪。按备份 `restore.sh` 回滚后，线上 launch MD5 已回到 `5550c580a4822e773a331bcef11f0c47`，下一批不得再使用本候选。旧 B-v3 独立紫球三局 `3/3` 删一球且 0 边界，是下一次组合验收的入口基线；其九局组合中仍有紫球追踪越界反例，须如实记录。

## 单变量 L：紫球接近速度降至 0.6 m/s

[第四批九局验收](../hit_balloon_part1_1.7/REPORT.md#第四批蓝球返航航点与冲刺后可见目标重对准)中紫球第三轮尚在 `APPROACHING` 就从 `y=-2.32` 逐步飞到 `-3.02`，随后搜索锚点又靠近边界。因此先只把**紫球**生成行为树中的 `forward_velocity` 默认值从 1.0 降到 0.6 m/s，红/蓝的前进速度、紫球冲刺速度 1.5 m/s、B 入场点和安全边界保持不变。用[MD5 锁定脚本](../../hit_balloon_v2/patches/patch_purple_approach_speed.py)对线上源码副本 dry-run 后部署，`bt_ros.cpp` 从 `9b1cefe9dfa431418435f7f8f63a60ed` 变为 `e9c266de8fc5d4d8a5df896788cdf3ee`；[实际 diff](deployed_purple_forward.diff)、[编译日志](purple_forward_build.log)、[重启日志](purple_forward_restart.log)和服务器备份 `/home/ubuntu/hit_balloon_purple_forward_backup_20261018T223228/` 保留。编译日志含 `bt_ros.cpp.o` 重建和可执行文件重新链接，首局生成树实读 `forward_velocity="0.600000"`。部署前第四批 `exit_code=0`、无正式锁、PX4 未武装；重启后场景 3 Actor。

独立紫球三局 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_purple_forward_speed_20261018/` 的循环 `exit_code=0`，[逐局汇总](purple_forward_summary.csv)与[原始证据包](purple_forward_evidence.tar.gz)保留每局连续 GC、真实帧窗口和 ROS 日志。三局均三球开局、`valid=1`，连续 GC 分别 107、87、68 次，共 **262 次、0 错误**；结局 **`3→2、3→2、3→3`**，边界 **0、0、1**。前两局物理删一球但未进入冲刺，也未记录独立气球阶段事件，不能据此证明冲刺安全。

第三局是明确反例：14:48:55.104 UTC 紫球在 `(4.234,-2.308,0.238)`、yaw `-1.363`、画面面积比 0.2565 时，以**仍为 1.5 m/s** 的速度冲刺；14:48:56.229 UTC 机体在 `(4.31,-3.05,0.48)` 触发 y 下界，冲刺结束于 `y=-3.158`，目标仍新鲜且在画面侧边（`err_x=304 px`）。[冲刺前紫球近景](evidence_purple_forward_r3/purple_near.jpg)与[冲刺后天空画面](evidence_purple_forward_r3/after_sprint_sky.jpg)及[连续帧包](purple_forward_r3_miss_frames.tar.gz)可以复核；连续 GC 与任务后、稳定快照始终是 3 只，**没有击破任何球**。正式观察器却给出 `mission_success=true`，是本局的假阳性，不能用其替代物理证据。

因此接近速度 0.6 m/s **单独不能通过**：三局仅 2/3 物理删球，1/3 边界。与第四批紫球 3/3 删一球、3/3 边界相比，样本和目标轨迹均不同，不能把边界数量变化直接归因于速度；新发现的是仍然独立存在的高速度冲刺漏击和越界。当前先保留此版本作为下一项紫球**冲刺速度**单变量试验的起点，若累计候选失败，按 `/home/ubuntu/hit_balloon_purple_forward_backup_20261018T223228/restore.sh` 恢复并重新编译。

## 单变量 M：紫球冲刺速度降至 0.6 m/s（两局有效，第三局环境中断；已回滚）

L 批第三局从 `(4.234,-2.308,0.238)` 以 1.5 m/s 冲刺，目标仍在视野侧边时到 `y=-3.158`，物理零删球且曾触发边界。因此只把紫球 `sprint_velocity` 默认值从 1.5 降至 0.6 m/s，保留 L 的紫球接近速度 0.6、红/蓝参数、入场坐标及安全边界不变。[MD5 锁定脚本](../../hit_balloon_v2/patches/patch_purple_sprint_speed.py)对 L 的 `bt_ros.cpp` `e9c266de8fc5d4d8a5df896788cdf3ee` 做字节校验，新值 `e15853ebe9f0c5136fff718558635814`；[线上 diff](deployed_purple_sprint.diff)、[编译日志](purple_sprint_build.log)、[重启日志](purple_sprint_restart.log)与备份 `/home/ubuntu/hit_balloon_purple_sprint_backup_20261018T225331/` 保留。编译重新链接 `bt_ros`，首局生成树实读 `forward_velocity="0.600000" sprint_velocity="0.600000"`。

远端独立批次 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_purple_sprint_06_20261018/` 的前两局已在三球开局、连续 GC 下记录各一次 `3→2`，各一次 y 边界；第一局 14:57:46.228 UTC 从 `y=-2.804` 开始冲刺，[破裂光点真实帧](evidence_purple_sprint_r1/purple_flash.jpg)在约 0.38 秒后出现，[后续画面](evidence_purple_sprint_r1/after_boundary.jpg)已无紫球，14:57:47.409 UTC 才触边 `y=-3.01`。第二局的边界在 15:04:17.649 UTC，**早于** 15:04:23.268 UTC 的冲刺启动。第三局 15:08 UTC 三球开局后服务器实例中断；恢复时 `trial_3_purple_1.log` 停在 `mission_once.py` 启动，旧 PID 均不存在，`trials.csv` 只有前两行且无循环 `exit_code`。第三局没有正式结局，**不得算入三局样本**；M 只有 2 局有效数据，不能判定优于第四批。

2026-10-19 世界坐标调查测得紫侧墙实体 `y=-2.801…-2.501`，软件下界 `-3.0` 已在墙外，详见[边界调查](../hit_balloon_part1_boundary_survey/REPORT.md)。本轮遵新验收口径不再增加紫色候选。确认无正式锁、PX4 未武装后，将线上 M 源码 MD5 `e15853ebe9f0c5136fff718558635814` 备份到 `/home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp.bak_20261019T0112`，从 `/home/ubuntu/hit_balloon_purple_forward_backup_20261018T223228/bt_ros.cpp` 恢复第四批源码，`touch`、`catkin_make --pkg mission_pkg -j2` 成功并重启；线上 MD5 回到 `9b1cefe9dfa431418435f7f8f63a60ed`。L/M 均不纳入最终九局。

## 回滚

先确认没有正式试验运行且机体已解除武装，再分别执行：

```bash
bash /home/ubuntu/hit_balloon_purple_extra_margin_backup_20261018T2115/restore.sh
bash /home/ubuntu/hit_balloon_blue_visible_retry_backup_20261018T2053/restore.sh
bash /home/ubuntu/hit_balloon_blue_return_via_backup_20261018T2040/restore.sh
bash /home/ubuntu/hit_balloon_blue_entry_interior_backup_20261018T1400/restore.sh
bash /home/ubuntu/hit_balloon_blue_contact_threshold_backup_20261018T1230/restore.sh
bash /home/ubuntu/hit_balloon_blue_sprint_speed_backup_20261018T115816/restore.sh
bash /home/ubuntu/hit_balloon_return_goto_backup_20261018T113556/restore.sh
bash /home/ubuntu/hit_balloon_red_interior_backup_20261018T0400/restore.sh
bash /home/ubuntu/hit_balloon_red_inner_backup_20261018T0345/restore.sh
bash /home/ubuntu/hit_balloon_red_clearance_backup_20261018T0330/restore.sh
bash /home/ubuntu/hit_balloon_red_avoid_blue_backup_20261018T0252/restore.sh
bash /home/ubuntu/hit_balloon_blue_contact_backup_20261018T0133/restore.sh
bash /home/ubuntu/hit_balloon_purple_boundary_backup_20261018T0230/restore.sh
bash /home/ubuntu/hit_balloon_purple_entry_tuned_backup_20261018T0113/restore.sh
bash /home/ubuntu/hit_balloon_purple_entry_backup_20261018T0052/restore.sh
```

先撤最新 B 余量、蓝球冲刺重试及蓝球返航航点，再按列表逆序恢复旧候选。C 向内入场在失败批次后已经撤回，重复执行其 restore 只会恢复同一 C 原坐标。每个 C++ 回滚都要确认 `touch` 后重新编译成功；若旧脚本在 `source /opt/ros/noetic/setup.bash` 时因 `set -u` 停止，应先核对已复制源码的 MD5，再以普通 shell 手工执行 `source /opt/ros/noetic/setup.bash && cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg -j2`。随后重启仿真，核对视觉舵机 MD5 `e440050ecfc06657d5ac4b472411fef6`、`bt_ros.cpp` MD5 `0ce0f6ec147d516d20e1a89d612792a6` 和 launch MD5 `cff7ff38bf7ac9ef98ee890a1c8644e8`。备份和全部原始试验目录保留。
