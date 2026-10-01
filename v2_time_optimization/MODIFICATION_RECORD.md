# V2 Patch 1 修改记录

## 范围

Patch 1 只替换 LLM 动态 `cross_frame` 中观察点后的固定 2 s `Delay`。新节点在行为树中观察 odometry：位置误差和速度同时满足阈值并连续保持确认时间后立即成功；达到 2 s 保守上限时也成功继续，以保持原 Delay 的任务失败语义。

V1 Safety Boundary Recovery 文件已作为输入复制到 `working_source`，未被修改：

- `src/mission_pkg/src/mavros_cnt.cpp`
- `src/mission_pkg/include/mavros_cnt.h`

## V2 工作文件

- `working_source/src/mission_pkg/src/bt_ros.cpp`
- `working_source/src/mission_pkg/launch/llm_mission.launch`
- `working_source/src/mission_pkg/include/nodes/action/wait_for_stable_position.h`
- `working_source/src/mission_pkg/src/nodes/action/wait_for_stable_position.cpp`
- V1 输入文件：`working_source/src/mission_pkg/src/mavros_cnt.cpp`、`include/mavros_cnt.h`

`CMakeLists.txt` 使用 `src/nodes/action/*.cpp` 自动 glob，新节点不需要新增构建清单条目。

## 参数

```text
optimization/position_threshold  = 0.15 m
optimization/velocity_threshold  = 0.08 m/s
optimization/stable_confirm_time = 0.50 s
optimization/settle_timeout       = 2.00 s
```

原 `cross_frame/observe_delay_ms=2000` 参数保留，确保旧配置兼容；动态 XML 以 `optimization/settle_timeout` 为等待上限，未设置时回退到旧 Delay 的秒数。

## 控制权与安全

`WaitForStablePosition` 不调用 `updateCommand()`，不发布新的 MAVROS、Ego-Planner 或感知控制消息。前一个 `GoTo` 完成时已经留下悬停设定点；等待节点只读取 `fcu_odom_ptr`。V1 的最终 publish 层 Safety Recovery 和 `current_cmd` 逻辑保持原样。

## 可回滚

完整 patch：`patches/v2_patch1_wait_for_stable_position.diff`。

恢复到 V1 输入文件：

```powershell
Copy-Item v2_time_optimization/backups/v1_input/src/mission_pkg/src/mavros_cnt.cpp <workspace>/src/mission_pkg/src/mavros_cnt.cpp -Force
Copy-Item v2_time_optimization/backups/v1_input/src/mission_pkg/include/mavros_cnt.h <workspace>/src/mission_pkg/include/mavros_cnt.h -Force
Copy-Item v2_time_optimization/backups/v1_input/src/mission_pkg/launch/llm_mission.launch <workspace>/src/mission_pkg/launch/llm_mission.launch -Force
Copy-Item v2_time_optimization/backups/official_pristine/src/mission_pkg/src/bt_ros.cpp <workspace>/src/mission_pkg/src/bt_ros.cpp -Force
Remove-Item <workspace>/src/mission_pkg/include/nodes/action/wait_for_stable_position.h -Force -ErrorAction SilentlyContinue
Remove-Item <workspace>/src/mission_pkg/src/nodes/action/wait_for_stable_position.cpp -Force -ErrorAction SilentlyContinue
```

备份输入 SHA256 在 `backups/SHA256SUMS.before_v2_patch1.txt`，工作文件 SHA256 在 `backups/SHA256SUMS.after_v2_patch1.txt`。

## 当前验证

- launch XML 解析通过。
- 生成的 `WaitForStablePosition` BT 片段 XML 解析通过。
- V1 两个 C++ 文件与输入备份 SHA256 一致。
- 尚未启动仿真；ROS 编译和三色正式测试需在 ROS 服务器工作区执行。
