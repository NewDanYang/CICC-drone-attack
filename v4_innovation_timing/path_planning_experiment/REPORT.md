# 非目标气球几何避让代价：两版限额概念验证（2026-10-20）

## 结论与止损

**方向 A 的优化目标函数确实能够参与 Ego-Planner 求解，但当前成果不能作为规则中独立的“创新、更换路径规划算法”10 分项申报。**第二版在真实仿真任务中有 4/7 条抽样优化器日志显示非零气球代价，红色任务正常完成；然而给优化器提供三维位置的是 UE 仿真器真值，并非可提交的传感器感知链路。当前部署没有可用的对齐深度图，彩色框与现有深度点云的直接投影出现背景点混入。按任务的两版上限及结构性障碍止损，不做第三版，不把真值桥接程序作为比赛代码运行，也不在 `innovation_nodes_draft.md` 中把它列为已验证加分节点。

本次从 09:23 到 10:16（北京时间）完成可行性观测、两版参数试验和服务器回滚，低于半天可行性与一天服务器占用上限。只跑红色 A0，每配置 1 局；紫、蓝未跑。因此没有“三色稳定提升”的结论。

## 一、可行性：占据栅格与颜色到三维位置

服务器 2026-10-20 的实际 [ROS 话题图快照](evidence/topic_graph_rollback_20261020.txt)中，`/objects` 由 `det_color.py` 从 `/rflysim/sensor1/img_rgb` 发布；Ego-Planner 虽订阅 `/rflysim/sensor1` 作为深度图，但该话题**没有发布者**。规划器的有效几何输入是 `/rflysim/sensor0/Depth_Cloud` 经 `cloud_transform_node.py` 变换的 `/cloud_registered`。因此任务提示中的“检测框同像素深度反投影”不能直接用于当前部署。

真实红色官方基线局中，[只读探针原始记录](evidence/feasibility_baseline_20261020.jsonl)有 124 个周期样本。`/grid_map/occupancy_inflate` 每次均有点；`/grid_map/occupancy` 均为 0，这是 `grid_map.cpp` 的 `cloudCallback()` 直接写膨胀缓冲区所致，不能把未膨胀话题的空值误判为规划器看不到障碍。以 UE 紫球包围盒中心做测量参考、把 UE z 号翻转到 ROS 世界系后，原始点云有 9/124 帧在中心 0.3 m 内出现点，说明至少有间歇性的近球几何信息。但在同时记录到紫色检测框的 29 帧中，这个严格的 0.3 m 条件是 0/29。目标在移动，UE 回包与 ROS 图像不是硬同步；这个计数**不能证明深度完全看不到气球**，只能说明现成链路尚不足以稳定产出带颜色的三维中心。

仿真重启后又做了 35 秒原地投影检查，共 [14 个真实样本](evidence/feasibility_projection_idle_20261020.jsonl)。将 `/cloud_registered` 按当前 90° 彩色相机的 320/320/320/240 像素内参投到 `/objects` bbox 内：首个红球框内虽有 16 个点，最近 20% 深度点的世界坐标中位数约 `(4.618, 1.303, 0.276)` m；同次 UE 红球包围盒中心换算为 `(4.117, 2.103, 0.448)` m，三维差约 0.96 m。紫球检测框内多次选出 `y≈-2.76…-2.90` m 的背景点，而紫球车道 UE `y≈-2.10` m。此检查没有完整的两传感器外参与时间配准，不能将误差全归因于某一个因素；也不能将框内最近点直接冒充目标三维位置。

为验证**代价函数本身**，后续两版仅在内部试验中使用 [UE 真值桥接程序](tools/ue_truth_poc_bridge.py)：从实际 `hit_balloon:red` 指令取得目标颜色，读取当前 UE 三只 Actor，按本场景车道给 Actor 归色，仅把非目标紫球（本次实际有新鲜回包者）作为 `PoseArray` 发到 `/planning/poc_non_target_balloons`。程序必须带 `--allow-ue-truth-poc` 才运行。车道归色和 UE 查询是仿真特权，**不满足最终方案的运行时真实感知要求**；本次没有把 UE 坐标硬编码进 C++ 或封存的 Part 1 飞行代码。

## 二、实现和两个版本

在官方原版 `BsplineOptimizer` 的 `combineCostRebound()` 新增独立项：

`C_balloon = lambda_balloon × Σ_i Σ_b max(0, clearance_balloon - ||q_i - b||)^3`

其中 `q_i` 是参与优化的 B-spline 控制点，`b` 是当前非目标球中心。梯度随同代价加入 L-BFGS，独立于原通用碰撞权重 `lambda2_`。每次 `rebound_optimize()` 开始时冻结一次有效位置列表，超过 2 秒无桥接消息则不使用；优化器日志记录非零代价评估次数。C++、头文件与依赖声明见独立封存的 [payload_v1](payload_v1/README.md)；部署采用 [MD5 校验及备份脚本](patches/patch_balloon_clearance_cost_v1.py)，将 `--payload-root` 指向 `payload_v1/`。先编译 `bspline_opt`，再编译依赖它且会实例化优化器的 `ego_planner`，两者均成功；编译日志见 [bspline_opt](evidence/build_v1.log)、[ego_planner](evidence/build_ego_v1.log)。

2026-10-27 存储位置修订：历史提交 `add1a2a` 将上述候选代码放入了 `official_baseline/`。本次已从其父提交恢复官方基线，同时按 `deployed_md5` 将候选四文件完整封存到 `payload_v1/`，见 [恢复校验记录](evidence/baseline_restore_20261027.json)。原补丁、部署清单、实验日志及数值保持原样；这次目录修复没有新增编译或仿真实验。

| 配置 | C++ 源 | 独立权重 | 避让中心距离 | 实际优化器抽样日志 |
|---|---|---:|---:|---|
| 官方原版 | MD5 `a968a5e81b3799c2ed68d75b582f5fc4` | 无 | 无 | 无此代价 |
| v1 | MD5 `c48a58affe333bfef509deba6b7ba43d` | 1.0 | 0.8 m | 活跃目标 1 个；7/7 条的非零评估次数均为 0 |
| v2 | 同一 C++，仅 [参数切换脚本](patches/patch_balloon_clearance_cost_v2.py) | 2.0 | 1.3 m | 活跃目标 1 个；4/7 条有非零评估，分别为 75、12、1、16 次 |

v1 的较大实测避让距离不是算法收益的证据，因为该代价在 v1 从未触发。v2 的非零计数只能证明目标函数参与了真实规划，尚不能单凭一次试验证明性能优于官方。

## 三、官方原版对照和真实任务结果

三局都在同一服务器、红色 A0、三球开局条件下完成。首局运行的是**未改动的官方 Ego-Planner**，其服务器 C++ MD5 与仓库官方快照一致；v1/v2 叠加于同一套已封存 Part 1 飞行代码。正式记录摘录为 [trial_outcomes.csv](evidence/trial_outcomes.csv)，每局的气球定位规划区间来自对应 [官方基线](evidence/baseline_red_planning_runs.csv)、[v1](evidence/v1_red_planning_runs.csv)、[v2](evidence/v2_red_planning_runs.csv) 原始 `planning_runs.csv`。

| 原版/候选 | 正式 run_id | 成功 | 总用时 | 气球定位规划用时 | 到非目标紫球最近距离（气球定位区间） | 该区间距离样本数 |
|---|---|---|---:|---:|---:|---:|
| 官方原版 | `20261020T093245_a7fc3b` | 是 | 99.948 s | 12.723 s | 0.871 m | 10 |
| v1 | `20261020T100031_702d95` | 是 | 97.201 s | 10.078 s | 1.325 m | 12 |
| v2 | `20261020T100907_5279f2` | 是 | 94.894 s | 10.518 s | 1.541 m | 12 |

距离按各观测时刻的 ROS 里程计与 UE 紫球包围盒中心计算，不是离线固定球坐标；计算可用 [summarize_poc.py](tools/summarize_poc.py) 从 [官方基线探针](evidence/feasibility_baseline_20261020.jsonl)、[v1 桥接日志](evidence/bridge_v1_red_20261020.jsonl)、[v2 桥接日志](evidence/bridge_v2_red_20261020.jsonl)重现。优化器原始日志分别见 [v1](evidence/cost_v1_red_20261020.log)和 [v2](evidence/cost_v2_red_20261020.log)。三局整体最小距离依次为 0.679、0.985、1.142 m，但前两者发生在气球定位规划区间之外，不应拿整体最小值代替本阶段指标。

**这些 1 对 1 对照不能支持成功率、用时或避让距离提升的统计结论。**移动球的相位和观测频率没有配对控制；v1 在代价完全未触发时也比官方局离球更远，是明确反例。v2 保持任务成功且代价被调用，是方向性的算法可运行证据，适用范围仅限本机红色 A0 的这一次 UE 真值概念验证。紫、蓝颜色以及最终传感器链路尚无结果。

服务器完整正式原件保留于：

- `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261020T093241_red_A0/`（官方原版）；
- `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261020T100026_red_A0/`（v1）；
- `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261020T100902_red_A0/`（v2）；
- `/home/ubuntu/tcei_baseline_tools/planning_probe/`（逐请求探针、桥接、编译和部署清单）。

## 四、异常、回滚和提交判断

三局正式任务均在 UE 退出前完成。查询探针参与的场景在正式任务结束后又出现 RflySim3D `SIGSEGV`（v2 为 10:11:08，北京时间，约在任务完成后 8 秒），v2 桥接程序在锁释放时已停止。故障发生在任务完成后，不能计为规划算法失败；现有证据也不足以把崩溃归因于 UE 查询、场景重置或其他单一原因。为避免重复占用共享服务器，未追加更多局。

**已实际回滚服务器**：运行 v1 补丁脚本的 `--rollback`，按 [部署清单](evidence/deploy_v1_manifest.json)将四个源码文件恢复至部署前 MD5；重新编译 `bspline_opt` 和 `ego_planner`，记录见 [回滚编译 1](evidence/rollback_build_bspline.log)、[回滚编译 2](evidence/rollback_build_ego.log)；重启仿真后验证原版 `ego_planner_node` 运行中、C++ 四文件 MD5 均与清单原值一致、库中没有 `calcBalloonClearanceCost` 符号、`/ego_planner_node/optimization/lambda_balloon_clearance` 参数不存在、无桥接进程与正式试验锁。可重复的回滚命令为：

```bash
python3 /home/ubuntu/tcei_baseline_tools/planning_probe/patch_balloon_clearance_cost_v1.py \
  --source-root /home/ubuntu/catkin_ws/src/ego-planner \
  --manifest /home/ubuntu/tcei_baseline_tools/planning_probe/deploy_v1_manifest.json --rollback
cd /home/ubuntu/catkin_ws
catkin_make --pkg bspline_opt -j4
catkin_make --pkg ego_planner -j4
```

第二次执行 `--rollback` 前需先按脚本核验当前版本；当前服务器**已经处于回滚后状态**，不应重复执行该命令。仓库里的修改仅用于代码评审和以后真正完成感知融合时复核，不建议当前合入正式参赛运行分支。达到“规则 10 分项”至少还缺：用传感器图像/点云稳定输出带颜色三维球位置、官方原版与候选在同口径下的多局真实对照、以及现场性能与技术文档一致性证明。
