# V2.1 max_vel 配置

每个候选目录包含一份 `FS-J310_ego-planner.launch` 和一份未修改的
`FS-J310_Param.xml` 参考副本。

候选值：

| 配置 | `max_vel` |
|---|---:|
| A0 | 0.30 |
| A1 | 0.35 |
| A2 | 0.40 |
| A3 | 0.45 |
| A4 | 0.50 |

A0 launch 与官方字节一致；A1–A4 launch 只改 `<arg name="max_vel">`。官方 `FS-J310_Param.xml` 将这个
arg 同时传给：

```text
manager/max_vel
optimization/max_vel
bspline/limit_vel
```

`max_acc=0.50`、planning horizon、replan 和障碍物参数均保持官方值。

运行前必须把候选 launch 部署到测试工作区，启动后检查：

```bash
rosparam get /ego_planner_node/manager/max_vel
rosparam get /ego_planner_node/optimization/max_vel
rosparam get /ego_planner_node/bspline/limit_vel
```

三项必须相同，且等于当前配置值。
