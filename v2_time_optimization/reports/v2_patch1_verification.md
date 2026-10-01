# V2 Patch 1 验证记录

## 已完成

- 独立工作副本建立于 `v2_time_optimization/working_source`。
- V1 `mavros_cnt.cpp` 和 `mavros_cnt.h` 已复制为输入并通过 SHA256 对比，未被 V2 改写。
- `llm_mission.launch` XML 解析通过。
- `WaitForStablePosition` 生成的行为树 XML 片段解析通过。
- 新节点被放在 `src/nodes/action`；现有 `CMakeLists.txt` 通过 glob 自动收录该 `.cpp` 插件，不需要修改官方构建清单。
- 原 `cross_frame/observe_delay_ms=2000` 参数保留；Patch 1 的 `settle_timeout=2.00` 保留原等待上限。
- 新等待节点不调用 `updateCommand()`，不发布额外 ROS 控制消息。

## 尚未完成

ROS 编译需要服务器上的 ROS Noetic、catkin 和消息依赖。当前尝试连接已授权服务器：

```text
ssh -p 30316 root@120.209.70.195
TCP connect: Connection refused
```

因此本轮尚未执行 `catkin_make --pkg mission_pkg`，也没有启动仿真或正式飞行测试。服务器恢复可达后应先编译，再进行红、紫、蓝三色单局回归。

## 编译命令

在服务器工作区应用 `working_source` 中的文件后执行：

```bash
source /opt/ros/noetic/setup.bash
source /home/ubuntu/catkin_ws/devel/setup.bash
cd /home/ubuntu/catkin_ws
catkin_make --pkg mission_pkg -j4
```

## 回归要求

每次只运行一局，记录：

- `mission_success`、`bt_success`
- `total_time`
- `cross_frame` 稳定等待实际耗时
- 三色任务是否触发 V1 Safety Recovery
- 是否出现 `stuck`、`interrupted` 或新的越界
