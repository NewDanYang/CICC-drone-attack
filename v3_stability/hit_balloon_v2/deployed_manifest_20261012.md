# 2026-10-12 服务器部署盘点

只读检查时间：2026-10-12 15:04–15:15（Asia/Shanghai）。主机 `120.209.70.195:30316`，容器主机名 `gpufree-container`。检查时无 `/tmp/tcei_formal_trial.lock`，`/home/ubuntu/hit_balloon_trials/` 不存在，`baseline_runs.csv` 最后一行是 2026-10-06 的试验。

## 版本与编译

| 文件（`/home/ubuntu/catkin_ws/` 下） | MD5 | 源文件修改时间（+08:00） |
|---|---|---|
| `src/mission_pkg/src/nodes/action/visual_servo.cpp` | `a97f5af29c2797e47a55bb3d7d216106` | 2026-03-20 14:48 |
| `src/mission_pkg/src/nodes/action/planning_control.cpp` | `905442c90a66ea1ed2443c895ac3ac51` | 2026-03-26 17:16 |
| `src/mission_pkg/include/nodes/action/planning_control.h` | `42a22cb424ebafe847f4a3528213e69d` | 2026-01-28 15:21 |
| `src/mission_pkg/src/bt_ros.cpp` | `8da042a25554563220c98555824b7d62` | 2026-10-01 14:40 |
| `src/mission_pkg/src/nodes/action/goto.cpp` | `f0710df499635efdc01dc8bd071ff018` | 2026-03-26 17:16 |
| `src/mission_pkg/src/mavros_cnt.cpp` | `edcd9397074f44c6028c8dca02902920` | 2026-10-06 11:33 |
| `src/mission_pkg/include/mavros_cnt.h` | `f6a6a2c8db2a63ab26c0125c7dd8ad51` | 2026-10-06 11:33 |
| `src/mission_pkg/src/base/target_detector_base.cpp` | `9e0af36ad105a51770c21c99d2732e3a` | 2026-03-11 14:16 |
| `src/mission_pkg/src/nodes/perception/target_tracker.cpp` | `d33701db820f199483b681a140ffd71e` | 2026-01-28 15:21 |
| `src/mission_pkg/scripts/aruco_detect_node.py` | `0f15e84bdaed68c85d3b6b6ee5e33788` | 2026-10-06 16:47 |
| `src/object_det/scripts/det_color.py` | `9eda726899abaf4f951f6b03a08c11ad` | 2026-03-27 09:06 |
| `src/mission_pkg/launch/llm_mission.launch` | `a1f0cfc65cd7357ab38c4a09ad4ef45a` | 2026-10-06 13:58 |
| `devel/lib/mission_pkg/bt_ros` | `6d3d38564f7295e0bb92458d4a4c52fd` | 2026-10-06 12:36 |

二进制时间晚于目前所有列出的 C++ 源码，因此**不能**仅凭时间认定当前源码未编译；但它早于交接所述 2026-10-11 补丁部署，且当前 `visual_servo.cpp` 仍是无居中冲刺门控、负号偏航、无限搜索的旧代码。安全恢复 `mavros_cnt.cpp/.h` 与交接给出的 MD5 一致。`llm_mission.launch` 中的 V2 `optimization/*` 四行仍在。

## PR #2 与服务器差异

本地 Git 提交 `1e86aaa4f94e6e6c95d67e538884ff7cb8f56c39` 已合入 `main`，包含 `v3_stability/hit_balloon_midterm/patches/` 下的脚本。服务器 `/home/ubuntu/` 没有交接记载的 `visual_sprint_alignment_v4_backup_20261011T025959`、`visual_yaw_direction_v1_backup_20261011T031447`、`bounded_visual_search_v3_backup_20261011T040040` 或 `hit_balloon_trials/`；在 `/home/ubuntu` 与 `/root` 下均未找到。因而不能将 PR #2 报告中的部署状态视为本实例的当前状态，也无法拷贝这些备份的 `changes.diff`。参见 [deployed_diffs/README.md](deployed_diffs/README.md)。

当前 `visual_servo.cpp` 原版 `ROS_INFO` 的 `SPRINT!` 语句有四个占位符、四个相应参数，**不存在**交接所述 V4 版本的格式错位；后续若恢复居中门控，需单独检查新日志格式。

## 行为树来源及参数

`/home/ubuntu/model/mission_once.py` 从 `/home/ubuntu/model/prompts/mission_prompt.txt` 构造大模型指令，发布 `/mission_command`。`src/mission_pkg/src/bt_ros.cpp:311–375` 把 `hit_balloon:<color>` 转换成 XML，包含 `ForceSuccess → Timeout(50000) → Parallel(TargetTracker, VisualServo)`，并在 `:491–493` 输出 `Generated BT XML` 到 ROS 日志。本目录的 [last_recorded_bt_20261006_red.xml](last_recorded_bt_20261006_red.xml) 从 2026-10-06 红色正式试验 `20261006T150929_red_A0/20261006T150933_35cad5_red_telemetry.jsonl` 提取，是**最近保留的真实下发 XML 示例**，不代表 10 月 11 日版本。

`bt_ros.cpp:335–343` 在生成 XML 时通过 `getDbl("visual_servo/…")` 从 ROS 参数服务器读取增益、面积、前进速度、冲刺速度和时长，然后写入 `<VisualServo …/>` 属性；`visual_servo.cpp:58–75` 再以 `getInput<>()` 读取 BT 端口。因此在**命令生成前**设置 `/visual_servo/sprint_velocity` 等参数可以生效。其实际值须以当局 `Generated BT XML` 和 `Visual Servo Started` 日志核对。`mission_once.py` 不直接决定这些数值。

## 适用范围

本清单只证明 2026-10-12 本实例的静态文件和历史日志状态。未启动仿真、未确认运行中的 ROS 参数或场景气球状态。原始历史试验仍在 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/`，检查时有 45 个目录；PR #2 的 10 月 11 日试验不在该实例中。

## 本日后续部署（不属于上表的初始快照）

初始盘点后，先部署仅增加冲刺起终点日志的补丁 `patches/patch_sprint_observability.py`：原源码 MD5 `a97f5af29c2797e47a55bb3d7d216106`，部署后 `0422136d865fd7a738a2fc434f45bffd`，编译后的独立插件 `/home/ubuntu/catkin_ws/devel/lib/visual_servo.so` MD5 `b60dbde79ac1e0869af91fdd47ad9ff2`。备份 `/home/ubuntu/sprint_observability_backup_20261012T1529/`。`bt_ros` 可执行文件本身不承载 VisualServo 插件，故其时间不必因插件重编译而改变。

在正式红球对照局 `20261012T153554_red_A0` 暴露出对齐死区问题后，部署 `patches/patch_alignment_deadzone.py`：源码从 `0422136d865fd7a738a2fc434f45bffd` 变为 `4d9a99091f3d1f68facb743d2fab14e2`，插件 MD5 `9edb6504ccc95154494560ac68a2d319`，备份 `/home/ubuntu/visual_alignment_deadzone_backup_20261012T1539/`。已完成 `catkin_make --pkg mission_pkg -j2`，并重启 `/llm_mission_node`；运行中仅有一个 `bt_ros` 进程。两次 C++ 补丁均未改动飞控安全边界、其他 C++ 源文件或 launch 文件。

在独立真实相机帧显示红球入场原朝向对墙后，另用 `patches/patch_red_entry_yaw.py` 仅将 `/balloon_zone_A/yaw` 从 `1.5708` 改为 `3.14159`。launch MD5 `a1f0cfc65cd7357ab38c4a09ad4ef45a` → `985fd7628fb4af120e63fdf6cea4e757`，备份 `/home/ubuntu/red_entry_yaw_pi_backup_20261012T1618/`，仿真重启后 ROS 参数确认 `3.14159`。该阶段实际文件的字节级快照见 `deployed_source/`；此项未修改 `optimization/*`、`safety/*`、ArUco、紫/蓝球航点或 V2 参数。

`20261012T163949_red_A0` 的红任务删去两个 Actor 后，用 `patches/patch_red_staging_height.py` 把红区两个同坐标的 z 从 `1.0` 抬到 `1.5`。launch MD5 `985fd7628fb4af120e63fdf6cea4e757` → `9088ac755b09854976bf62a643ddf4bd`，备份 `/home/ubuntu/red_staging_height_backup_20261012T1650/`。`deployed_source/llm_mission.yaw_only.launch` 保留上一版，`deployed_source/llm_mission.high_end.launch` 保留该全程高位版。其他参数不变。

该全程高位版在 `20261012T165314_red_A0` 没有红色像素跟踪，但 Actor 延迟减少一个。再用 `patches/patch_red_final_descent.py` 仅把红区末端 `goal` z 恢复为 `1.0`，保留高位 `approach_pos` z=`1.5`。launch MD5 `9088ac755b09854976bf62a643ddf4bd` → `3fdc18d0f61052da1e93456078370926`，备份 `/home/ubuntu/red_final_descent_backup_20261012T1700/`。`deployed_source/llm_mission.high_end.launch` 保留全程高位版，`deployed_source/llm_mission.launch` 为当前分段高度版。

分段高度单独试验 `20261012T170422_red_A0` 的冲刺偏心，Actor 3→3→3，遂部署 `patches/patch_sprint_center_gate.py`。源码 MD5 `4d9a99091f3d1f68facb743d2fab14e2` → `74802b9d2082aa408b97b555685aee2a`，插件 MD5 `b64a48261667657d62655e2fb659d2df`，备份 `/home/ubuntu/sprint_center_gate_backup_20261012T1709/`。单独回归 `20261012T171054_red_A0` 门控生效但前推丢目标后仍假 SUCCESS，Actor 3→3→3。再部署 `patches/patch_close_align_reacquire.py`，源码 MD5 `74802b9d2082aa408b97b555685aee2a` → `b09abd4b545d89cef8135913b9dc06b3`，插件 MD5 `1d6aa1634a813c8392f0286406bcc420`，备份 `/home/ubuntu/close_align_reacquire_backup_20261012T1715/`。两次均经 `catkin_make --pkg mission_pkg -j2` 成功编译、重启任务节点并核对进程映射；源码快照依次见 `deployed_source/visual_servo.deadzone_only.cpp`、`visual_servo.gate_only.cpp`、`visual_servo.cpp`。

`20261012T171720_red_A0` 居中冲刺仍误删蓝球后，部署 `patches/patch_red_heading_guard.py`：`visual_servo.cpp` MD5 `b09abd4b545d89cef8135913b9dc06b3` → `418ae9129a266bc4ac3c013f4232011b`，`visual_servo.h` → `1093026e507c382d075fe00cfbef64b4`，`bt_ros.cpp` `8da042a25554563220c98555824b7d62` → `989415357ddcc33777989026ce873eca`；备份 `/home/ubuntu/red_heading_guard_backup_20261012T1735/`。BT 现在把目标颜色传给视觉伺服；红球面积达标但与朝向 π 差超过 0.45 rad 时阻止前冲/冲刺，同时移除冲刺前丢目标的假 SUCCESS。`catkin_make --pkg mission_pkg -j2` 成功，重启后核对插件映射。`20261012T173621_red_A0` 红 Actor 删除、最终降落成功但全局任务失败。保存的真实动态 BT XML 见 `generated_bt_20261012_red.xml`。

`patches/patch_yaw_probe.py` 是临时诊断版；C++ `418ae912` → `047c`（完整 MD5 见备份），header `1093` → `fc84`，ROS 参数 `/visual_servo/yaw_probe=true`。固定 ±0.2 rad/s 的实测记录在 `evidence/20261012T1753_yaw_probe.log`，使用 `20261012T175348_red_A0` 正式局。随后执行 `/home/ubuntu/yaw_probe_backup_20261012T1752/restore.sh`，重新编译并重启，参数恢复 `false`，不作为当前控制版本。

`20261012T181001_purple_A0` 在目标紫球早已消失的场景中，零机体系速度搜索漂移约 2.5 m。部署 `patches/patch_search_position_hold.py`，使丢目标搜索保持失联瞬间的世界坐标位置并扫描 yaw：`visual_servo.cpp` `418ae9129a266bc4ac3c013f4232011b` → **`e440050ecfc06657d5ac4b472411fef6`**，header `1093026e507c382d075fe00cfbef64b4` → **`d3324b0458b2160102f9bbf44546d035`**，插件 `1991d332fb6a8e28ca98d16b479de466`；备份 `/home/ubuntu/search_position_hold_backup_20261012T1816/`。编译/节点重启后 `20261012T181709_purple_A0` 搜索位置保持在 `(5.17,-1.93)` 附近；因紫球已不存在，该局只能验证位置行为，不能验证紫球成功率。当前服务端源码快照见 `deployed_source/visual_servo.cpp/.h`。

`20261012T184356_blue_A0` 正式输入要求蓝球，模型却生成 `hit_balloon:purple`。部署 `patches/patch_mission_color_guard.py` 到 `/home/ubuntu/model/mission_once.py`，MD5 `dcc050dd1daa1792a7312345932d0fcb` → **`4b0ae381b683b7c38d30baf808ed1346`**；备份与回滚脚本在 `/home/ubuntu/mission_color_guard_backup_20261012T1850/`。补丁只在文本任务明确指定一种气球颜色时，核对完整命令块恰有同色 `hit_balloon`；首次错色重试一次，仍错色则不发布。原模型生成/自然语言任务入口不变。本地 Python AST 解析和四个行为样例通过，服务器 `/opt/conda/envs/demo/bin/python3 -m py_compile` 通过。`20261012T185145_blue_A0` 的模型首答蓝色、BT 目标蓝色；此局尚未实测重试分支。服务端源码快照见 `deployed_source/mission_once.py`。

最终已核对服务端 `visual_servo.cpp=e440050ecfc06657d5ac4b472411fef6`、`mission_once.py=4b0ae381b683b7c38d30baf808ed1346`、`llm_mission.launch=3fdc18d0f61052da1e93456078370926`。`20261012T18:58+08:00` 为下一个独立场景发出重启命令后，SSH 端口 30316 连接被拒绝；场景是否完成启动**未核实**，应由 gpufree.cn 控制台恢复后重新检查 ROS 图、进程与 MD5。
