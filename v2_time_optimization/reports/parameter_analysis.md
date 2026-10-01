# Ego-Planner 参数分析

## 当前值

来源：`official_baseline/catkin_ws/src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch` 和同目录 `FS-J310_Param.xml`。

| 参数 | 当前值 | 使用位置 | 时间影响 |
|---|---:|---|---|
| `manager/max_vel` / `optimization/max_vel` / `bspline/limit_vel` | 0.3 m/s | PlannerManager、优化器、B-spline 物理限制 | 直接限制长距离规划速度 |
| `manager/max_acc` / `optimization/max_acc` / `bspline/limit_acc` | 0.5 m/s² | 初始多项式、优化器、B-spline | 直接影响加速和刹车段 |
| `manager/max_jerk` | 4 | B-spline/轨迹约束 | 影响平滑程度和可行性 |
| `manager/planning_horizon`、`fsm/planning_horizon` | 2.5 m | 局部规划范围 | 影响局部目标和重新规划频率 |
| `fsm/planning_horizen_time` | 3 s | FSM | 影响局部时间窗口 |
| `fsm/thresh_replan` | 1.0 m | FSM | 距离起点超过该阈值时重新规划 |
| `fsm/thresh_no_replan` | 1.0 m | FSM | 接近终点时不再重新规划 |
| `manager/control_points_distance` | 0.1 m | PlannerManager | B-spline 控制点采样密度 |
| `manager/feasibility_tolerance` | 0.05 | 可行性检查 | 允许的速度/加速度超限比例 |
| `bspline/limit_ratio` | 1.1 | B-spline | 物理限制检查比例 |
| `grid_map/resolution` | 0.05 m | 障碍地图 | 影响碰撞检查和优化开销 |
| `grid_map/obstacles_inflation` | 0.25 m | 障碍膨胀 | 影响可行路径和绕行长度 |
| `traj_server/time_forward` | 1.0 s | `traj_server` | 轨迹输出向前采样时间 |
| FSM 执行周期 | 0.01 s | `ego_replan_fsm.cpp` | 不是任务等待瓶颈 |
| 碰撞检查周期 | 0.05 s | `ego_replan_fsm.cpp` | 不是任务等待瓶颈 |

## 为什么短距离仍可能需要十几秒

`planner_manager.cpp` 用 `max_vel` 和 `max_acc` 计算初始轨迹时间：

```text
dist <= max_vel² / max_acc  -> sqrt(dist / max_acc)
否则                      -> (dist - max_vel²/max_acc)/max_vel + 2*max_vel/max_acc
```

当前 `max_vel²/max_acc = 0.18 m`。因此 3 至 4 m 级别的目标，即使没有障碍，也有约 11 至 15 s 的加减速下界；实际还要加上 B-spline 优化、局部重规划、障碍膨胀、轨迹切换和 `checkArrival()` 的 0.15 m 位置收敛要求。日志中的第一次穿框 PlanningControl 平均 19.065 s、气球区 PlanningControl 平均 15.799 s，与这套保守速度上限一致。

FSM 在 100 Hz 运行，碰撞检查在 20 Hz 运行，因此审计没有证据表明“tick 太慢”是主要问题。`traj_server/time_forward=1.0` 和 2.5 m 局部 horizon 可能影响轨迹衔接，但不能仅凭日志安全地改小或改大。

## 参数变更结论

本阶段不修改 Ego-Planner 参数。提高 `max_vel` 或 `max_acc` 的确有最大时间收益，但会同时改变穿框、返框、气球区和越界风险；需要独立的仿真批次、速度/加速度/安全边界指标和三色回归后再考虑。`planning_horizon`、障碍膨胀和 `time_forward` 也不应作为第一 patch。
