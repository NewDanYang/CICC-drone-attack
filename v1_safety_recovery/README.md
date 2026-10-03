# V1 Safety Boundary Recovery 使用说明

本目录保存当前 V1 安全恢复覆盖层。它只作用于 `mission_pkg` 的三份文件，
不改变九格输入、Behavior Tree 任务顺序、Ego-Planner、VisualServo 或感知算法。

## 当前版本

V1 使用两个不同的边界余量形成滞回：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `safety/recovery_target_margin` | `0.30 m` | 越界后计算恢复目标点时，目标点距离外边界的内缩量 |
| `safety/release_margin` | `0.15 m` | 释放恢复状态时要求飞机进入的内侧边界 |
| `safety/recovery_confirm_time` | `0.50 s` | 在释放边界内连续保持的时间 |

外边界仍为 `x=[-1.0,6.0]`、`y=[-3.0,3.0]`、`z=[-0.1,2.5]`，安全检查仍保持启用。

状态机只有两个状态：

```text
NORMAL --越过外边界--> RECOVERING
RECOVERING --连续 0.50 s 位于 release boundary 内--> NORMAL
```

进入 `RECOVERING` 时，系统按当前位置逐轴 clamp 到外边界向内 `0.30 m` 的最近点，
并保持进入恢复时的 yaw。恢复期间只在最终 MAVROS publish 层临时覆盖输出；
Behavior Tree、GoTo、PlanningControl 和 VisualServo 仍可更新共享的 `current_cmd`。
恢复完成后直接发布当时最新的 `current_cmd`，不会恢复旧命令快照。

关键日志：`[SafetyRecovery] ENTER`、`RELEASE confirmation started`、
`RELEASE confirmation reset`、`[SafetyRecovery] COMPLETE`。

## 将 V1 应用到远端工作区

先确认远端工作区没有未保存的人工修改，再执行以下命令。命令只复制本目录的三份
overlay 文件，不会覆盖其它官方文件：

```bash
cd /home/ubuntu/CICC-drone-attack
rsync -av v1_safety_recovery/src/mission_pkg/src/mavros_cnt.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/mavros_cnt.cpp
rsync -av v1_safety_recovery/src/mission_pkg/include/mavros_cnt.h \
  /home/ubuntu/catkin_ws/src/mission_pkg/include/mavros_cnt.h
rsync -av v1_safety_recovery/src/mission_pkg/launch/llm_mission.launch \
  /home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch
cd /home/ubuntu/catkin_ws
catkin_make --pkg mission_pkg
```

启动 `llm_mission.launch` 后，用 `rosparam get` 检查三个参数和外边界值，
再进行人工批准的单局测试。V1 本身不启动仿真，也不提交任务。

## 验证和回滚

修改前后应保存三份文件的 SHA256，并确认 `git diff --name-only` 只包含这三份文件。
仓库中的 `src/mission_pkg/` 是可审阅的 V1 overlay；`backups/` 只作为本地回滚材料，
不会随工具发布。

恢复官方版本时，从你在远端保存的原始备份复制三份文件，然后重新编译：

```bash
cp /path/to/original/mavros_cnt.cpp /home/ubuntu/catkin_ws/src/mission_pkg/src/mavros_cnt.cpp
cp /path/to/original/mavros_cnt.h /home/ubuntu/catkin_ws/src/mission_pkg/include/mavros_cnt.h
cp /path/to/original/llm_mission.launch /home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch
cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg
```

不要用实验日志或备份覆盖官方工作区；它们不属于 V1 运行时输入。
