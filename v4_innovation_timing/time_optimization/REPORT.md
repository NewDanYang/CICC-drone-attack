# 用时优化候选验证报告

日期：2026-10-22

最终状态：候选 1（起飞重试间隔 1.5 s）与候选 2（WaitForStablePosition）保留；候选 3（Ego-Planner 0.40 m/s）已回滚到 0.35 m/s。候选 1+2 做了红、紫、蓝各 1 局合并确认。

## 结论

候选 1 是本轮最明确的时间收益。在候选 2 基线之上，红、紫、蓝各 3 局的起飞均值分别为 9.531 s、7.817 s、8.525 s，9 局的起飞、第一次穿框、识码、逆穿框和降落全部成功。两次红色 300 s 超时是 PX4 停在 AUTO.LAND、模式请求持续 TEMPORARILY_REJECTED 的环境故障，未计为算法失败。

候选 2 已经在服务器当前源码中。本轮观测 3 色 × 3 局，9 局前置阶段全部成功；7/9 局在 0.516 s 稳定确认后继续，2/9 局到 2.002 s 上限后继续。没有把旧工作副本覆盖到服务器，因此不能宣称严格的同日 A/B 时间因果。

候选 3 的 0.40 m/s 版本 9 局前置阶段全部成功，第一次穿框均值比当前 0.35 m/s 观测低约 2.5–3.1 s，但逆穿框没有一致收益（紫色一局 26.609 s），并有 4 次安全边界事件。它已回滚，不部署。

## 证据范围

结论覆盖起飞、第一次穿框、识码、逆穿框、降落。hit_balloon 的成功率原样保留，不作为用时候选的成功判定。每个独立候选红、紫、蓝各 3 局，合并确认各 1 局；阶段成功按观测器 stage 事件判定。

正式试验目录已迁移到服务器数据盘 /root/gpufree-data/time_opt_formal_trials_archive_20261022，原路径保留符号链接。原始 JSONL 和 baseline_runs.csv 均保留。

## 候选 1：起飞重试间隔 5.0→1.5 s

只改 drone_action_node.h：

~~~
throttledSetMode(..., interval_sec = 1.5);
throttledArm(..., interval_sec = 1.5);
~~~

历史真实日志 n=11：OFFBOARD 均值 0.434 s、P95 0.957 s、最大 0.993 s；ARM 均值 0.406 s、P95 0.879 s、最大 0.975 s。部署前 MD5 7334b435faceae983f46f3dd185da172，部署后 c415ddd8243afcc64c181be45bdac5e3；catkin_make --pkg mission_pkg -j4 返回 0。

| 颜色 | 三次起飞时间（s） | 均值 | 前置成功 | 原始目录 |
|---|---:|---:|---|---|
| 红 | 9.104 / 8.373 / 11.115 | 9.531 | 3/3 | 20261021T231131_red_A0；20261021T233844_red_A0；20261022T002356_red_A0 |
| 紫 | 6.951 / 8.041 / 8.458 | 7.817 | 3/3 | 20261021T232522_purple_A0；20261021T234324_purple_A0；20261022T002913_purple_A0 |
| 蓝 | 8.838 / 8.347 / 8.391 | 8.525 | 3/3 | 20261021T233327_blue_A0；20261021T234939_blue_A0；20261022T003326_blue_A0 |

时间从 mission_start 到 takeoff_status=success。候选 1 前的同服务器红色对照 20261021T225149_f1aae0 为 12.930 s；历史 24 局均值为 16.0 s，后者跨越多个部署状态，仅作背景。

20261021T235526_red_A0 和 20261022T000808_red_A0 为环境超时：起飞阶段没有 OFFBOARD 确认，日志反复出现 SET_MODE TEMPORARILY_REJECTED。两次均清理残留任务并重启仿真，不能证明候选 1 造成失败。

结论：采用候选 1，与候选 2 合并确认；收益声明仅限起飞阶段。

## 候选 2：WaitForStablePosition

本轮前服务器已经包含该节点。bt_ros.cpp MD5 9b1cefe9dfa431418435f7f8f63a60ed，llm_mission.launch MD5 5550c580a4822e773a331bcef11f0c47。参数为位置阈值 0.15 m、速度阈值 0.08 m/s、连续确认 0.5 s、上限 2.0 s。

| 颜色 | 三次起飞时间（s） | 稳定等待结果 | 前置成功 |
|---|---:|---|---|
| 红 | 10.192 / 8.003 / 7.715 | 确认 / 确认 / 上限 | 3/3 |
| 紫 | 8.332 / 8.450 / 7.744 | 确认 / 确认 / 确认 | 3/3 |
| 蓝 | 8.477 / 7.935 / 8.162 | 上限 / 确认 / 确认 | 3/3 |

有效目录：红 20261022T004604_red_A0、20261022T011011_red_A0、20261022T012735_red_A0；紫 20261022T005355_purple_A0、20261022T011935_purple_A0、20261022T014501_purple_A0；蓝 20261022T005832_blue_A0、20261022T012258_blue_A0、20261022T014832_blue_A0。

紫色 20261022T013110_purple_A0 因根分区写满产生 OSError: [Errno 28] No space left on device，只有不完整日志，已排除并由 20261022T014501_purple_A0 补测。7/9 次确认耗时 0.516 s，2/9 次达到 2.002 s 上限。结论：保留；数据证明不会阻塞前置阶段，但不能把潜在 1.484 s 节省写成严格 A/B 因果收益。

## 候选 3：Ego-Planner max_vel=0.40

现场原值 0.35 m/s，先核对三个 ROS 参数均为 0.35，再将 launch 单行改为 0.40。部署前 MD5 1d9a148929c850c529f17fa3d421959f，部署后 c25f1f6587f5ed516efd5c49a5c76aad；9 局运行时三个参数均为 0.40。回滚后当前 MD5 恢复 1d9a148929c850c529f17fa3d421959f，三个参数均为 0.35。

| 颜色 | 第一次穿框（s，均值） | 逆穿框（s，均值） | 前置成功 | 边界事件 |
|---|---:|---:|---|---:|
| 红 | 17.608 / 15.591 / 17.910（17.036） | 12.892 / 15.386 / 12.981（13.753） | 3/3 | 0 |
| 紫 | 16.001 / 17.486 / 15.977（16.488） | 16.161 / 26.609 / 16.601（19.790） | 3/3 | 3 |
| 蓝 | 15.593 / 17.692 / 18.022（17.102） | 11.582 / 14.352 / 12.161（12.698） | 3/3 | 1 |

当前 0.35 m/s 观测下第一次穿框均值为红 19.562 s、紫 19.255 s、蓝 20.189 s。0.40 m/s 的第一次穿框收益存在，但逆穿框没有一致收益，紫色 26.609 s 是反例。4 次边界记录来自 20261022T020633_dd3f0b、20261022T022059_13950e、20261022T184718_6edfe1、20261022T185416_d426bd，均位于气球搜索/视觉伺服时段或其邻近时刻，未伴随前置阶段失败。结论：不采用 0.40 m/s，已回滚，不继续测 A1/A3/A4。

## 合并确认：候选 1 + 候选 2

候选 3 回滚并重启环境确认 0.35 m/s 后，重新编译部署候选 1，候选 2 保持原状态：

| 颜色 | 起飞（s） | 第一次穿框（s） | 逆穿框（s） | 前置成功 | 原始 JSONL |
|---|---:|---:|---:|---|---|
| 红 | 10.624 | 20.919 | 14.052 | 是 | /home/ubuntu/tcei_baseline_tools/results/formal_trials/20261022T213514_red_A0/logs/20261022T213518_7c88b9_red.jsonl |
| 紫 | 9.192 | 22.879 | 13.300 | 是 | /home/ubuntu/tcei_baseline_tools/results/formal_trials/20261022T214043_purple_A0/logs/20261022T214047_a48541_purple.jsonl |
| 蓝 | 9.237 | 21.513 | 14.378 | 是 | /home/ubuntu/tcei_baseline_tools/results/formal_trials/20261022T214549_blue_A0/logs/20261022T214553_ac2364_blue.jsonl |

合并确认 3/3 前置成功；紫、蓝各 1 次边界事件在气球视觉伺服时段，红色无边界事件。

## 当前部署、回滚和校验

当前服务器 MD5：

~~~
drone_action_node.h  c415ddd8243afcc64c181be45bdac5e3  # 候选 1，1.5 s
bt_ros.cpp            9b1cefe9dfa431418435f7f8f63a60ed  # 候选 2
llm_mission.launch    5550c580a4822e773a331bcef11f0c47  # 候选 2
FS-J310_ego-planner.launch  1d9a148929c850c529f17fa3d421959f  # 候选 3 已回滚，0.35 s
~~~

候选 1 回滚后需重新编译并重启 llm_mission_node：

~~~
python3 /tmp/patch_candidate1_throttle.py \
  --source /home/ubuntu/catkin_ws/src/mission_pkg/include/base/drone_action_node.h \
  --manifest /home/ubuntu/tcei_baseline_tools/time_optimization/candidate1_manifest.json \
  --rollback
cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg -j4
~~~

候选 3 回滚命令（已执行）：

~~~
python3 /tmp/patch_candidate3_max_vel.py \
  --source /home/ubuntu/catkin_ws/src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch \
  --manifest /home/ubuntu/tcei_baseline_tools/time_optimization/candidate3_manifest.json \
  --rollback
~~~

本地补丁 MD5：patch_candidate1_throttle.py ceb181672cb50f97c720ec9cd7bb5e13；patch_candidate2_wait_stable.py 54bd17249aeb3207d593cafe71044f95；patch_candidate3_max_vel.py a1b9201794af1b0b7da9c8745b77123b。候选 2 本轮没有覆盖服务器源码，因此没有新增候选 2 manifest。

最终建议：保留候选 1+2，停止现场试验；候选 3 的 0.40 m/s 只作为有边界的速度证据，不部署。
