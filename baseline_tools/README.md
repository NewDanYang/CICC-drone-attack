# TCEI baseline observer

本目录独立于 `/home/ubuntu/catkin_ws`，不会修改官方源码树。

## 运行单个颜色任务

首先加载 ROS 环境以及已经编译好的工作空间：

```bash
source /opt/ros/noetic/setup.bash
source /home/ubuntu/catkin_ws/devel/setup.bash
```

然后一次只运行一个实验：
```bash
python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py --color red
python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py --color purple
python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py --color blue
```

默认模式会启动官方 /home/ubuntu/model/mission_once.py，并通过命令行参数（argv）传入所选颜色对应的自然语言任务，同时关闭 stdin。
它不会发布预先构造好的任务命令。
如果官方 mission_once 终端已经在运行，可以使用：
```bash
--no-launch-llm
```

此时 observer 会立即启动，并将第一次收到 /mission_command 的时间记录为：
```bash
mission_start_time
```

--pre-mission-timeout（默认 900 秒）和 --mission-timeout（默认 300 秒）是两个独立的超时窗口。
其中：
- pre-mission-timeout 用于等待第一条 /mission_command；
- mission-timeout 只有在收到第一条 /mission_command 后才开始计时；
- 如果发生 pre-mission timeout，不会生成伪造的 CSV 结果。
输出文件：
- results/baseline_runs.csv
- results/logs/<run>.jsonl
observer 订阅以下 topic：
- /mission_command
- /mission_result
- /rosout
- /aruco/detected_id
- /objects
- /mavros/state
- /mavros/setpoint_raw/local
- /planning/pos_cmd
observer 不会向任何 ROS topic 发布消息。
各阶段字段只会根据明确的节点名称、日志消息或直接结果 topic 进行填充。
对于无法明确判断的阶段，对应字段保持为空。
不会使用 GoTo 的执行序号来推断阶段。
从源码中确认的官方链路
模块	源码	节点 / 进程	接口与作用
自然语言 LLM	/home/ubuntu/model/mission_once.py; mission_prompt.txt	mission_once	从 stdin 或 argv 读取输入，使用本地 FM9G4B-V 模型，并向 /mission_command 发布 std_msgs/String。
动态任务行为树	src/mission_pkg/src/bt_ros.cpp; launch/llm_mission.launch	llm_mission_node	订阅 /mission_command 和 /mission_abort；动态生成 XML；向 /mission_result 发布结果。
BT Action / Plugin 节点	src/mission_pkg/src/nodes/action、src/mission_pkg/src/nodes/perception、src/mission_pkg/src/base	从 devel/lib 加载的插件	包括 Takeoff、GoTo、PlanningControl、Land、TargetLocator、TargetTracker、ArucoDetector、VisualServo。
框架 / 气球感知	src/object_det/scripts/det_color.py; detection_color.launch	object_detection_node / det_color	/rflysim/sensor1/img_rgb → YOLO + HSV → /objects（common_msgs/Objects）。
ArUco	src/mission_pkg/scripts/aruco_detect_node.py; aruco_detect.launch; perception/aruco_detector.cpp	aruco_detect_node; BT ArucoDetector	使用 /rflysim/sensor2/img_rgb；通过 /aruco/enable 控制；识别结果发布到 /aruco/detected_id。
RflySim 输入	src/sensor_pkg/main.py	main.py	将 VisionCaptureApi 数据转换为 ROS 消息，包括图像、IMU 和 odom。
地图 / 随机化	src/sensor_pkg/AgentContestMap.py	AgentContestMap.py	负责 UE4 / RflySim 中目标物体摆放，以及红 / 蓝 / 紫气球场景配置。
点云	src/sensor_pkg/cloud_transform_node.py; cloud_transform.launch	cloud_transform_node	/rflysim/uav1/local/odom + /rflysim/sensor0/Depth_Cloud → /cloud_registered。
Ego-Planner	src/ego-planner/plan_manage 和 FS-J310_ego-planner.launch	ego_planner_node, traj_server, waypoint_generator, grid_map	使用 /move_base_simple/goal、RflySim odom 和点云进行规划，并输出 /planning/pos_cmd 及相关轨迹 topic。
MAVROS / PX4 桥接	src/mission_pkg/src/base/mavros_cnt.cpp 和 drone_action_node.cpp	BT Action 连接层	使用 mavros/state、mavros/set_mode、mavros/cmd/arming 和 /mavros/setpoint_raw/local。
Setpoint 监视	sim_env_start.sh	rostopic echo	仅观察 /mavros/setpoint_raw/local。


sim_env_start.sh
该脚本首先：
- source devel/setup.bash
- 可选加入 RflySim SDK
- 执行 kill_ros_pid.sh
- 启动 roscore
随后按顺序执行：
1. 在 xterm 中启动 mission_once.py
2. 在 xterm 中启动 detection_color.launch
3. MAVROS 启动命令被注释掉
4. 启动 src/sensor_pkg/main.py
5. 启动 src/sensor_pkg/AgentContestMap.py
6. 启动 sensor_pkg/cloud_transform.launch
7. 在 xterm 中启动 mission_pkg/aruco_detect.launch
8. 在 xterm 中启动 ego_planner/FS-J310_ego-planner.launch
9. 在 xterm 中启动 mission_pkg/llm_mission.launch
10. 在 xterm 中执行 rostopic echo /mavros/setpoint_raw/local
11. 启动一个资源监视 xterm
脚本会等待 /objects topic 出现，然后才启动 llm_mission。
脚本末尾提供了一些直接发布预构造 JSON 任务命令的示例。
baseline 工具刻意不使用这些示例，因为它们会绕过官方 LLM 自然语言任务链。
正式测试编排
服务器重启或仿真环境完全重置后，只需要启动一次共享仿真环境：
bash ./start_sim_environment.sh

启动脚本首先运行：
/home/ubuntu/PX4PSP/SITLRun.sh

并保持其交互式生命周期持续运行。
等待 20 秒后，再启动：
/home/ubuntu/catkin_ws/sim_env_start.sh

脚本使用锁机制防止重复启动，并将日志保存到：
/tmp/tcei_sim_environment

不要为每种颜色任务重复运行该启动脚本。
可以通过以下环境变量修改路径或启动等待时间：
TCEI_PX4_ROOT
TCEI_WS_ROOT
TCEI_SITL_STARTUP_DELAY

以及脚本中记录的其他 TCEI_* 变量。
由于官方 sim_env_start.sh 中 MAVROS 启动命令被注释掉，因此启动辅助脚本首先只等待：
- ROS graph 正常建立；
- RflySim odometry 持续输出。
随后检查 /mavros 是否存在。
如果不存在，则使用当前已有的 MAVROS 桥接方式启动：
roslaunch mavros px4.launch fcu_url:=udp://:20101@

然后等待：
/mavros/state

报告：
connected: true

这种启动顺序可以避免等待一个官方 sim_env_start.sh 本身并不会创建的 topic。
MAVROS 输出保存到：
/tmp/tcei_sim_environment/mavros.out

启动辅助脚本本身不会提交任务。
官方 sim_env_start.sh 在初始化 ROS graph 时可能会打开一个旧版交互式 LLM 终端。
正式测试脚本会在每次测试开始前清理残留的 mission_once.py 进程，然后只启动当前测试所需的、通过 argv 传入任务的 mission_once.py。
运行正式单局测试
使用 run_formal_trial.sh 执行一次非交互式官方任务测试：
bash ./run_formal_trial.sh red

该脚本会依次检查：
- ROS 是否就绪；
- MAVROS 是否就绪；
- LLM 节点是否就绪；
- /objects 是否正常；
- planner 是否正常。
随后：
1. 获取独占 trial lock；
2. 清理残留的 mission_once.py 进程；
3. 启动 observer；
4. 执行以下命令：
python3 mission_once.py "<natural-language task>"

observer 使用两个独立的超时窗口：
- --pre-mission-timeout：等待第一条 /mission_command；
- --mission-timeout：从收到第一条 /mission_command 后开始计时，并等待 /mission_result。
正式测试脚本会一直持有 trial lock，直到：
- observer 结束；
- mission_once.py 结束。
整个正式测试过程不会重启：
- ROS；
- SITL；
- RflySim。
