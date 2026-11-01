# 5.6c：容差复测完成——容差不是瓶颈，真正问题是接近阶段跟丢

日期：2026-11-01（北京时间）。本次复测严格按照 `docs/astra-handoff-fm9g-visualservo-tolerance-retry.md` 执行：每次单局前完整重启仿真环境（先 `cleanup_sim.sh` 确认进程清零和锁清空，再 `start_sim_environment.sh` 等 `environment_started=1`，再确认 `armed=False` 且里程计在起点附近），任务 0（对照，不改代码）、任务 1（20px）、任务 2（30px）各跑了恰好一局，结束后已把 `visual_servo.cpp/.h` 和编译产物全部还原到冻结值并重新编译核对。

## 结论

**三局证据一致指向同一个结论：对齐容差（8/20/30 px）不是瓶颈，真正的瓶颈是进入 APPROACH 之后跟踪跳动导致很快又丢失目标，从未积累到 8% 的冲刺面积阈值。** 不建议采用任何容差改动，已恢复冻结版本。红紫近距离丢失规则沿用 Astra 5.6b 的回测结论（**回测发现误触发风险，未部署**），本轮未重新验证。

## 1. 三局总表

| 任务 | 颜色 | 容差 | 完整重启 | 是否 Aligned | 进入 APPROACH | APPROACH 持续 | 峰值面积 | 是否 SPRINT | BT 结果 |
|---|---|---:|---|---|---|---:|---:|---|---|
| 任务 0（对照） | 红 | 8/10（冻结默认） | 是 | 是（err -3,8） | 是 | ~5 s | 0.7% | 否 | `bt_success=true` |
| 任务 1 | 红 | 20/20 | 是 | **否** | **否** | — | — | 否 | `bt_success=true` |
| 任务 2 | 紫 | 30/30 | 是 | 是（err 10,-17） | 是 | ~1.4 s | 0.6% | 否 | `bt_success=true` |

三局前置阶段（起飞、穿框、ArUco、回穿）全部成功，三局都在气球阶段超时（50 s `Timeout` 装饰器触发）后，由外层 `ForceSuccess` 把 BT 判定为 `SUCCESS`；观测器的 `mission_success=false, failure_stage=hit_balloon` 和这次研究无关——它和 5.5/5.6 已经记录过的问题一样，是观测器不认这种"超时后仍返回 SUCCESS"的模式，不代表三局都真的失败或成功，需要看 VisualServo 原始日志。

## 2. 任务 0（对照，8px 默认）：进入 APPROACH，但面积涨得很慢就丢了

红色 `20261101T162801_red_A0`，全程 125.26 s。进入击球阶段后搜索约 15 秒，在 08:29:50.10 触发 `Aligned! err:(-3,8) -> APPROACHING`。随后 APPROACH 持续约 5 秒：

```
08:29:50.11  APPROACH err:(-3,8)   area:0.4%
08:29:52.65  APPROACH err:(-9,33)  area:0.4%
08:29:53.15  APPROACH err:(-50,12) area:0.6%   ← err_x 从 -9 跳到 -50
08:29:53.66  APPROACH err:(-76,-4) area:0.6%
08:29:54.17  APPROACH err:(-63,-82) area:0.7%  ← err_y 从 -4 跳到 -82
08:29:55.29  Off-center target lost after approach; return to ALIGN and search.
```

面积从 0.4% 缓慢涨到 0.7%，离 8% 的冲刺阈值还差一个数量级，这时候误差本身开始剧烈跳动（err_y 一步跳了 78 px），随即丢失目标，之后两段共约 60 秒的原地搜索（分别约 1 圈和约 1.5 圈）都没有再检测到目标，直到 50 s 超时。

## 3. 任务 1（20px）：全程只有一次检测，而且这次检测本身就超出了 20px 容差

红色 `20261101T165046_red_A0`，全程 127.30 s，补丁 md5 `b8f4201d684e4386b9e003500902bd47`（与 Astra 5.6b 记录的值完全一致），插件 md5 `bc9b1f5327472840f663da536acf684b`（同上）。日志开头即为：

```
08:52:11.61  k_p_yaw_rate=... deadzone=20.0
08:52:11.62  Off-center target lost after approach; return to ALIGN and search.
```

进入击球阶段后两段共约 50 秒的原地搜索中，全程只出现过**一次**检测：

```
08:52:24.64  ALIGN - err:(298,186) yaw_rate:-0.500 vz:-0.300 stable:0
```

误差 298 px 远超 20px 容差（也远超 8px 默认容差），这次检测之后立刻又丢失目标，再搜索约 36 秒后超时。**本局没有出现任何 `Aligned!`、`APPROACHING` 或 `area:` 字样**，比对照局表现更差，说明问题不在于容差太严，而在于能不能获得任何有意义的连续检测。

## 4. 任务 2（30px）：第二次独立对齐，APPROACH 持续时间反而更短

紫色 `20261101T170214_purple_A0`，全程 145.57 s，补丁 md5 `6fbb6a2c288165f276c0302fe21fcf5f`、插件 md5 `51c3f7a470b58d393bb2671c4f28ad90`（均与 Astra 记录一致）。进入击球阶段后，第一段约 1 秒的检测出现剧烈误差（-239, 150 → -166, 141 → **-294**, 35 → -104, 114，几次之间跳动动辄 100–200 px），随即丢失，原地搜索约 17 秒。第二段检测触发对齐：

```
09:04:30.46  ALIGN - err:(10,-17) stable:1
09:04:30.50  Aligned! err:(10,-17) -> APPROACHING
09:04:30.51  APPROACH err:(23,-17) area:0.6%
09:04:31.02  APPROACH err:(59,-15) area:0.6%   ← err_x 跳了 36 px
09:04:31.52  APPROACH err:(59,-15) area:0.6%
09:04:31.87  Off-center target lost after approach; return to ALIGN and search.
```

这次 APPROACH 只维持了 1.36 秒就丢失，比默认 8px 容差那次（约 5 秒）更短。之后又是一长串剧烈跳动的检测（err 一度到 -304）夹杂多段搜索，始终没有再次稳定对齐，直到超时。

## 5. 为什么不是容差的问题

把容差从 8px 放宽到 20px、30px，预期应该让"进入 APPROACH"更容易、更稳定。但实测结果是：20px 这组一次都没能进入 APPROACH（比不放宽还差），30px 这组进入了但维持时间更短。三组误差本身在多次之间跳动的幅度（50–300 px）远大于三组容差设置之间的差异（8/20/30 px），说明**误差读数本身的跳动是主导因素，容差这个"读数要落在多小的窗口内才算对齐"的判据，在读数本身就会突然跳动 100+ px 的情况下，调大几像素到几十像素没有意义**。

这和 5.6 报告里对近距离大气球框面积系统性偏小（约为真实面积的 0.28–0.47 倍）、以及框在扫描窗口与上一帧框之间做正反馈收缩的发现是一致的：框本身不稳定，偶尔跳动，才是接近阶段反复跟丢、面积涨不上去的根本原因。

## 6. 红紫近距离丢失规则

本轮没有重新验证。沿用 Astra 5.6b 的回测结论：扩展到红紫会在历史真实追踪成功局中造成提前误判（见 `multimodal_5_6b_align_tolerance/REPORT.md` 和 `evidence/rule_backtest_summary.md`），**未部署**。

## 7. 最终状态与回滚核对

三局结束后执行的还原步骤（均已完成）：

1. `visual_servo.cpp` 从 30px 备份目录恢复，md5 核对为 `a63b57fa127a23cd8bb8e647f078ff21`（冻结值）。
2. `visual_servo.h` 全程未改动，md5 `d3324b0458b2160102f9bbf44546d035`（冻结值）。
3. `catkin_make --pkg mission_pkg -j2` 重新编译，`devel/lib/visual_servo.so` md5 为 `6ddfa7c180ae18f5097efd95d369b97f`，与冻结值完全一致。
4. 清理所有仿真进程（`bt_ros`/`px4`/`CopterSim`/`RflySim3D`/`roscore`/`mavros_node`）和锁文件（`/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`、`/tmp/px4_lock-*`），服务器恢复为无正式试验锁、无残留进程的空闲状态。

补丁备份目录（本轮新建，避免与 Astra 5.6b 的同名目录冲突）：

- `/home/ubuntu/visualservo_tolerance_backup_20261101b_20px/`
- `/home/ubuntu/visualservo_tolerance_backup_20261101b_30px/`

## 8. 建议

1. **不要继续沿"放宽对齐容差"这个方向调参**，三组数据已经说明这条路走不通。
2. 下一步如果要继续研究 hit_balloon，应该针对"APPROACH 阶段框跳动导致跟丢"本身：可能方向包括提高跟踪帧率、给面积估计加时间平滑（但要小心 5.6 已经发现简单滑动平均会让中心误差变差，面积和中心可能需要分开处理）、或者放宽"丢失判定"而不是"对齐判定"的容忍度（比如允许短暂的大误差读数不算丢失，只有连续多帧都异常才判定丢失）——最后这一条和 5.6b 已经回测过的红紫近距离丢失规则是两回事，不要混淆。
3. 阶段 D 的 9+9 回归可以在**冻结默认容差**下按计划进行（`docs/astra-handoff-fm9g-stage-d.md` 解除暂停），但基于本轮三局证据，应该预期候选的命中率很低——这不是本轮新发现的缺陷，是现有候选在当前跟踪稳定性下的真实上限，阶段 D 的意义是拿到统计样本，而不是指望这次回归能打中更多。

## 9. 复现

```bash
# 任务 0（对照，不改代码）
bash tools/cleanup_sim.sh
# 确认进程和锁清空后
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
cd /home/ubuntu/tcei_baseline_tools && bash ./start_sim_environment.sh
# 等 environment_started=1，确认 armed=False、里程计在起点附近
bash ./run_formal_trial.sh red

# 任务 1/2：先 bash tools/cleanup_sim.sh + 完整重启，再
python3 tools/patch_deadzone.py 20 /home/ubuntu/visualservo_tolerance_backup_<新目录名>_20px
cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg -j2
# 跑一局；结束后用同一个备份目录里的 visual_servo.cpp 还原，重新编译核对二进制 md5
```

原始证据：`evidence/control_*`、`evidence/d20_*`、`evidence/d30_*`（各自的 `observer.out`、`mission_once.out`、完整 rosout `*.jsonl`）。
