# TCEI baseline observer

This directory is independent of /home/ubuntu/catkin_ws and does not modify the
official source tree.

## Run one color

Source ROS and the built workspace first:

    source /opt/ros/noetic/setup.bash
    source /home/ubuntu/catkin_ws/devel/setup.bash

Then run exactly one experiment:

    python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py --color red
    python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py --color purple
    python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py --color blue

The default mode starts the official /home/ubuntu/model/mission_once.py with
the natural-language sentence for the selected color. It does not publish a
prebuilt command. If the official mission_once terminal is already running,
use --no-launch-llm; observer starts immediately and records the first /mission_command receipt as mission_start_time.

Output:
- results/baseline_runs.csv
- results/logs/<run>.jsonl

The observer subscribes to /mission_command, /mission_result, /rosout,
/aruco/detected_id, /objects, /mavros/state, /mavros/setpoint_raw/local and
/planning/pos_cmd. It never publishes to any ROS topic.

Stage fields are populated only from explicit node names/messages or direct
result topics. Ambiguous stages remain blank. No GoTo ordinal is used.

## Official chain found in source

| Area | Source | Node/process | Interfaces and role |
|---|---|---|---|
| Natural language LLM | /home/ubuntu/model/mission_once.py; mission_prompt.txt | mission_once | Reads stdin/argv, local FM9G4B-V model, publishes /mission_command (std_msgs/String). |
| Dynamic mission BT | src/mission_pkg/src/bt_ros.cpp; launch/llm_mission.launch | llm_mission_node | Subscribes /mission_command and /mission_abort; creates XML; publishes /mission_result. |
| BT action/plugin nodes | src/mission_pkg/src/nodes/action and src/mission_pkg/src/nodes/perception; src/mission_pkg/src/base | plugins loaded from devel/lib | Takeoff, GoTo, PlanningControl, Land, TargetLocator, TargetTracker, ArucoDetector, VisualServo. |
| Frame/balloon perception | src/object_det/scripts/det_color.py; detection_color.launch | object_detection_node / det_color | /rflysim/sensor1/img_rgb -> YOLO + HSV -> /objects (common_msgs/Objects). |
| ArUco | src/mission_pkg/scripts/aruco_detect_node.py; aruco_detect.launch; perception/aruco_detector.cpp | aruco_detect_node; BT ArucoDetector | /rflysim/sensor2/img_rgb; /aruco/enable; /aruco/detected_id. |
| RflySim input | src/sensor_pkg/main.py | main.py | VisionCaptureApi ROS translation, image/IMU/odom feeds. |
| Map/randomization | src/sensor_pkg/AgentContestMap.py | AgentContestMap.py | UE4/RflySim object placement and red/blue/purple balloon setup. |
| Point cloud | src/sensor_pkg/cloud_transform_node.py; cloud_transform.launch | cloud_transform_node | /rflysim/uav1/local/odom + /rflysim/sensor0/Depth_Cloud -> /cloud_registered. |
| Ego-Planner | src/ego-planner/plan_manage and FS-J310_ego-planner.launch | ego_planner_node, traj_server, waypoint_generator, grid_map | /move_base_simple/goal and RflySim odom/cloud -> /planning/pos_cmd and trajectory topics. |
| MAVROS/PX4 bridge | src/mission_pkg/src/base/mavros_cnt.cpp and drone_action_node.cpp | BT action connection | mavros/state, mavros/set_mode, mavros/cmd/arming, /mavros/setpoint_raw/local. |
| Setpoint monitor | sim_env_start.sh | rostopic echo | Observes /mavros/setpoint_raw/local only. |

## sim_env_start.sh

The script sources devel/setup.bash, optionally adds the RflySim SDK, runs
kill_ros_pid.sh, starts roscore, then:
1. mission_once.py in xterm
2. detection_color.launch in xterm
3. MAVROS command is commented out
4. src/sensor_pkg/main.py
5. src/sensor_pkg/AgentContestMap.py
6. sensor_pkg/cloud_transform.launch
7. mission_pkg/aruco_detect.launch in xterm
8. ego_planner/FS-J310_ego-planner.launch in xterm
9. mission_pkg/llm_mission.launch in xterm
10. rostopic echo /mavros/setpoint_raw/local in xterm
11. a resource-monitor xterm

It waits for /objects before starting llm_mission. The helper examples at the end
of the script publish prebuilt JSON commands; the baseline tool deliberately
does not use those examples because they bypass the official LLM path.
