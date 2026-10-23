# 1.3 冲刺近目标刹车的独立九局验收（2026-10-16）

## 改动与测量

部署前核对服务器 `visual_servo.cpp` MD5 为 `e440050ecfc06657d5ac4b472411fef6`；补丁脚本 [patch_sprint_abort_on_contact.py](../../hit_balloon_v2/patches/patch_sprint_abort_on_contact.py) 仅在 `SPRINTING` 分支加入面积、目标滑向边缘或近距离丢失的提前悬停判据，修改后 MD5 为 `e3db3675fce56abe68e71f73963f0b0a`。[部署差异](deployed_sprint.diff)仅 23 行新增，`catkin_make --pkg mission_pkg -j2` [编译成功](build.log)并重启仿真。1.4 的 `bt_ros.cpp` 和 launch 在本批试验中未改。

每局都重新查 UE 三球 Actor，缺球先重启场景，开真实相机帧采集；红、紫、蓝各三局、A0 档位，共 **9 局有效**。[summary.csv](summary.csv)含每局正式目录、Actor 数、越界、冲刺与提前刹车日志；[evidence/](evidence/)保留 `trials.csv`、场景原始快照、ROS 事件和关键真实帧。服务器完整原始目录为 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_part1_3_20261016T0115/`，每个正式目录由 `trials.csv` 给出，不能将不同 `sim_pid` 的 Actor-ID 映射跨局复用。

| 局 | 目标 | Actor 3→结局 | 目标色相机判读 | 越界 | 冲刺／提前刹车 |
|---:|---|---:|---|---:|---:|
| 1 | 红 | 3→2 | 红球与小车同框，下一帧同处小车上方已无红球 | 0 | 0／0 |
| 2 | 紫 | 3→2 | 紫球贴近后出现破裂亮光 | 1 | 1／1，`passed_target`，刹车后 0.259 秒越界 |
| 3 | 蓝 | 3→2 | 蓝球贴近后镜头转向；目标是否消失不能独立确认 | 0 | 1／1，`area` |
| 4 | 红 | 3→2 | 红球贴近后下一帧可见破裂亮光 | 0 | 0／0 |
| 5 | 紫 | **3→1** | 紫球贴近后镜头转向，目标是否消失未独立确认；至少一只非目标球被删 | 0 | 1／1，`area` |
| 6 | 蓝 | **3→1** | 蓝球贴近后下一帧可见破裂亮光；另至少一只非目标球被删 | 0 | 0／0 |
| 7 | 红 | 3→2 | 红球贴近后镜头转向，目标是否消失未独立确认 | 0 | 0／0 |
| 8 | 紫 | 3→2 | 紫球贴近后镜头转向，目标是否消失未独立确认 | 1 | 0／0 |
| 9 | 蓝 | **3→1** | 蓝球占据画面左侧后镜头转向；目标是否消失未独立确认，至少一只非目标球被删 | 1 | 1／0 |

逐帧判读见 [manual_color_review.csv](manual_color_review.csv)。第 4 局红球自动色块脚本将较晚的砖墙红色误当成气球，因此表中的真气球证据采用 17:30:13.288–14.368 UTC 的 [真实帧](evidence/batch1/r2_red_a1/real_frames/20261015T173013_288321Z_0110.jpg)与[破裂下一帧](evidence/batch1/r2_red_a1/real_frames/20261015T173014_368140Z_0111.jpg)，没有采用 `hit_timing_candidate.json` 给出的 17:31:01–02 假候选。其余自动时间窗也只作为找帧线索，不当作物理碰撞时间真值。

## 验收结论

与 [1.1 同条件未改动的九局](../hit_balloon_part1_1.1/REPORT.md)相比：Actor 恰少一球从 **7/9 降至 6/9**；额外删球从 **2/9 升至 3/9**，独立误击下界至少三只；越界从 **6 次／4 局**降至 **3 次／3 局**，仍高于要求的 **≤1/9**。历史 2026-10-13 的 7/9 越界没有逐局三球开局保证，只作背景，正式对照用 1.1。九局共 4 次冲刺、3 次提前刹车；第 8 局无冲刺仍越界，第 9 局冲刺未提前刹车也越界，第 2 局提前刹车仍越界。代码仅作用于 SPRINTING，无法涵盖这些反例。

按严格帧证据，第 1、2、4、6 局可确认指定球破裂，另外五局由于镜头转向没有相同强度的颜色确认。1.1 报告的 8/9 使用了“目标贴近后不再入镜 + Actor 减少”的宽口径；若沿用该口径，1.3 的多局也可能计入，但两个口径不能混用来宣称击破率不下降。无论按哪个口径，本项边界验收已**不通过**，且 3→1 的反例多于改前，不能称为稳定修复。

## 回滚、范围与后续

服务器源码备份 `/home/ubuntu/hit_balloon_sprint_backup_20261016T0110/` 含字节原件、原 MD5、差异和 `restore.sh`。1.3 验收失败后已在正式试验结束、飞控解锁时还原源码。旧备份脚本的 `cp -p` 保留时间戳，首次 `catkin_make` [跳过了重编](rollback_initial_build.log)；随后对还原的 `visual_servo.cpp` 执行 `touch`，再次编译，日志明确显示 [C++ 对象重建并链接 `.so`](rollback_forced_build.log)，再重启仿真。当前线上 `visual_servo.cpp` MD5 已恢复为 `e440050ecfc06657d5ac4b472411fef6`。本仓库补丁脚本生成的新回滚脚本已加 `touch`。若再次需要回滚同一备份，执行：`bash /home/ubuntu/hit_balloon_sprint_backup_20261016T0110/restore.sh && touch /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp && cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg -j2`，确认有 `Building CXX object ... visual_servo.cpp.o` 和链接日志后重启仿真。原始正式数据应保留。

这九局只代表本服务器、三球新场景、A0 档位和这组阈值；没有重复第二组九局，也没有随机交错对照。额外删球的具体颜色无法由跨重启的 Actor ID 判断。下一步若要消除无冲刺的误击/越界，需要另立针对 APPROACHING 和目标丢失行为的独立实验，不能把它们记作本次冲刺分支修复的效果。
