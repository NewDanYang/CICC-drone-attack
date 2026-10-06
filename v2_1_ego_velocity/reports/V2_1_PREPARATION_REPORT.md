# V2.1 Ego-Planner 准备报告

## 参数实际作用链

官方启动文件：

```text
official_baseline/catkin_ws/src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch
  -> include FS-J310_Param.xml
  -> arg max_vel
  -> /ego_planner_node/manager/max_vel
  -> /ego_planner_node/optimization/max_vel
  -> /ego_planner_node/bspline/limit_vel
```

`FS-J310_Param.xml` 中三项都直接使用 `$(arg max_vel)`。节点启动时：

- `planner_manager.cpp` 读取 `manager/max_vel`；
- `bspline_optimizer.cpp` 读取 `optimization/max_vel`；
- `UniformBspline::setPhysicalLimits()` 使用 `bspline/limit_vel`；
- launch 中没有动态 reconfigure 接口，因此实验必须重启 Ego-Planner。

源码还表明 `max_vel` 参与初始轨迹时间分配、B-spline 物理约束和 replan 采样步长。

没有发现另一处对 Ego-Planner 正常水平飞行施加 0.30 m/s 的固定限制。任务源码中的
VisualServo、Land 等速度常数属于其他控制阶段，本阶段不修改。

## 已准备配置

`configs/A0` 到 `configs/A4` 分别为 0.30、0.35、0.40、0.45、0.50 m/s。
每个目录中的 Param XML 是官方未修改参考副本，候选 launch 只改变 max_vel arg。

## Observer / logger

`baseline_tools/run_baseline.py` 新增可选 `--v21-telemetry` 模式：

- 记录 `/mavros/local_position/odom`；
- 同时记录实际规划输入 `/rflysim/uav1/local/odom`；
- 记录 `/planning/pos_cmd`；
- 记录 `/mavros/setpoint_raw/local`；
- 按 Generated BT XML 将 PlanningControl 标为
  `first_cross_frame_planning`、`return_cross_frame_planning`、
  `balloon_positioning_planning`；
- 计算 duration、start/end xyz、odom path length、平均/峰值速度、最终位置误差、
  planner/setpoint 速度、replan 计数、安全恢复和碰撞证据；
- 独立写入 V2.1 telemetry JSONL 与 `planning_runs.csv`；默认 baseline CSV 不变。

## 当前状态

- A0–A4 已准备。
- 官方 baseline 与 V1 Safety Recovery 未修改。
- Python 静态编译和 XML 解析已通过；A0–A4 的 max_vel 值分别为
  0.30、0.35、0.40、0.45、0.50 m/s。
- 尚未启动仿真或正式飞行。

本机为 Windows 工作站，未安装 ROS/catkin，因此本轮没有伪造 `catkin_make`
结果。由于只修改了 observer Python 文件和独立配置副本，已完成 Python 编译、
XML 解析、`git diff --check` 与官方目录改动检查；实际 ROS 编译应在云端工作区
部署候选配置后执行。

## 实验切换与恢复

每次只部署一个候选 launch，重启 Ego-Planner 后检查三项参数：

```bash
rosparam get /ego_planner_node/manager/max_vel
rosparam get /ego_planner_node/optimization/max_vel
rosparam get /ego_planner_node/bspline/limit_vel
```

observer 使用 `--v21-telemetry --v21-config A0 --v21-max-vel 0.30`（将 A0 和
数值替换为当前档位），一局结束后停止并分析，再切换下一档。恢复官方/V1 当前
状态时运行：

```powershell
powershell -File .\v2_1_ego_velocity\restore_v2_1_configs.ps1 `
  -WorkspaceRoot C:\path\to\catkin_ws
```

该脚本只恢复 Ego-Planner 的 A0 launch/Param 副本，不接触 V1 Safety Recovery。
