# 1.4 红区无固定入场 yaw 的独立验证（2026-10-16）

## 修改与部署

先完成并出具 [1.3 的九局失败验收](../hit_balloon_part1_1.3/REPORT.md)，再修改红区。部署前服务器 `bt_ros.cpp` MD5 为 `989415357ddcc33777989026ce873eca`，`llm_mission.launch` MD5 为 `3fdc18d0f61052da1e93456078370926`。[MD5 限制的补丁脚本](../../hit_balloon_v2/patches/patch_red_entry_perception.py)仅改这两个文件：A 区生成的 `GoTo` 不再传 `yaw`，A 区 `approach_pos` z 从 1.5 改为 0.7，并删除 A 区 launch yaw 参数；B/C 的运行 XML 分支不变。修改后 MD5 分别为 `0ce0f6ec147d516d20e1a89d612792a6`、`cff7ff38bf7ac9ef98ee890a1c8644e8`。见[实际差异](deployed_red_entry.diff)与[编译日志](build.log)；launch XML 解析通过。重启后 ROS 参数实测 A 区 `approach_pos=5.3;1.0;0.7`，A 区 yaw 参数不存在；正式日志写出 `yaw=visual_servo`。

**该改动的精确范围**：去掉的是红区入场 `GoTo` 的预设朝向。现有 `balloon_zone_A/goal=5.3;1.0;1.0` 和 `approach_pos` 仍是固定世界坐标；`visual_servo.cpp` 原有的红球冲刺航向安全门仍要求接近 ±π 后才允许冲刺。首批一局真实日志显示视觉舵机从约 1.67 rad 扫到 −2.965 rad 后冲刺，说明扫描实际发生，也说明当前不能宣称整段红球行为完全无预设朝向或位置点。比赛规则中“预设位置点”的合规性仍须对这些固定坐标单独审查。

## 两批独立红球试验

每局先核实三球 Actor、缺球重启环境，再采集真实帧；均为 A0 档位。红球 1.3 对照是 **3/3 恰少一球、0/3 越界、0/3 冲刺**。

| 运行配置 | 红球局数 | 三球开局→恰少一球 | 越界事件／局 | 冲刺／提前刹车 | 原始汇总 |
|---|---:|---:|---:|---:|---|
| 1.3 对照：原入场 + 冲刺刹车 | 3 | 3/3 | 0／0 | 0／0 | [1.3 summary.csv](../hit_balloon_part1_1.3/summary.csv) |
| 1.4 首批：新入场 + 1.3 刹车 | 3 | 3/3 | 1／1 | 1／1 | [combined_summary.csv](combined_summary.csv) |
| **1.4 单独部署：新入场 + 原冲刺** | **3** | **3/3** | **0／0** | **0／0** | [standalone_summary.csv](standalone_summary.csv) |

首批目的是验证线上生成命令和运行链路，但一局触发了 1.3 的提前刹车，不能作为 1.4 独立归因。之后在无正式任务、飞控解锁时撤回 1.3：由于旧 `restore.sh` 的 `cp -p` 会让 Make 跳过重编，实际对还原的 `visual_servo.cpp` 执行 `touch` 并确认 [对象重建与共享库链接](../hit_balloon_part1_1.3/rollback_forced_build.log)，重启后才跑**单独部署**三局。单独部署期间 `visual_servo.cpp` MD5 为原值 `e440050ecfc06657d5ac4b472411fef6`；`bt_ros.cpp` 与 launch 仍为上面的 1.4 新 MD5。三局均无冲刺，因此不存在 1.3 刹车路径混入。

真实帧显示单独部署三局的红球在近距离占据画面后，于相邻 1.0–1.1 秒采样帧中消失；每局 Actor 数仅减一。见 [standalone_evidence](standalone_evidence/) 的 `real_frames/`、`scene_snapshots.jsonl` 与 `hit_timing_candidate.json`，逐局严格颜色判读见 [manual_color_review.csv](manual_color_review.csv)。这是与 1.3 红球对照相同的“目标贴近后消失 + Actor 减少”判读口径，**3/3 未低于对照的 3/3**。但三局下一帧均有视角变化，不能仅凭 Actor-ID 独立确认消失的那只就是红球；严格的颜色身份确认仍有缺口。首批三局的 [combined_evidence](combined_evidence/) 也保留；其中第一局后续帧同屏可见蓝、紫球，配合仅少一球，能独立支持红球被删。自动 HSV 色块在砖墙场景会产生假候选，报告采用人工复核真实帧，不把候选时间当精确碰撞时间。

## 原始数据、结论与回滚

首批服务器目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_part1_4_20261016T1824/`；单独部署目录 `/home/ubuntu/tcei_baseline_tools/results/hit_balloon_part1_4_standalone_20261016T1840/`。各自的 `trials.csv` 给出三局正式目录，正式目录里有完整遥测、快照、帧及观察器记录。各批的 `sim_pid` 不同，没有沿用旧 Actor-ID 颜色映射。

**验收边界**：按“3→2 + 红球近距离出现随后消失”的既定宽口径，1.4 单独部署红球为 3/3，与改前 3/3 持平，越界 0/3；可保留为红区入场候选。3 局不足以估计比赛成功概率，严格的目标颜色身份证据也不足以宣称已经完全稳定或完全规则合规。A 区与 C 区的 `approach_pos` 现在同为 `5.3;1.0;0.7`，虽然三局红球未出现 3→1，仍需在后续三色交错试验检验误击风险。1.3 冲刺补丁因全色验收失败已撤回，不属于当前部署状态。

服务器备份 `/home/ubuntu/hit_balloon_red_entry_backup_20261016T1820/` 保存两个字节原件、MD5、diff、`restore.sh`。若要撤回 1.4，先确认无正式试验且 `armed: False`，执行 `bash /home/ubuntu/hit_balloon_red_entry_backup_20261016T1820/restore.sh && touch /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp && cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg -j2`，确认实际重编 `bt_ros.cpp.o` 和链接，再重启仿真。本仓库新补丁脚本生成的回滚脚本已加入 `touch`；服务器现存旧备份仍须按上述命令强制重编。试验原始数据应保留。
