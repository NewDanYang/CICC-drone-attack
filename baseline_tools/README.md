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
the natural-language sentence for the selected color with argv input and
stdin closed. It does not publish a prebuilt command. If the official
mission_once terminal is already running, use --no-launch-llm; observer starts
immediately and records the first /mission_command receipt as
mission_start_time.

`--pre-mission-timeout` (default 900 seconds) and `--mission-timeout` (default
300 seconds) are separate. The latter starts only after the first
`/mission_command`; a pre-mission timeout does not create a CSV result.

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

## Formal trial orchestration

Start the shared simulation environment once after a server reboot or a full
environment reset:

    bash ./start_sim_environment.sh

The startup helper launches `/home/ubuntu/PX4PSP/SITLRun.sh` first, keeps its
interactive lifetime open, waits 20 seconds, and then launches
`/home/ubuntu/catkin_ws/sim_env_start.sh`. It keeps a lock and logs under
`/tmp/tcei_sim_environment`; do not run it again for each color. Override paths
and startup delay with `TCEI_PX4_ROOT`, `TCEI_WS_ROOT`,
`TCEI_SITL_STARTUP_DELAY`, or
the other `TCEI_*` variables documented in the script.

Because the official `sim_env_start.sh` has its MAVROS launch line commented
out, the helper first waits only for the ROS graph and live RflySim odometry.
It then checks for `/mavros`; if it is absent, it starts the existing bridge
with `roslaunch mavros px4.launch fcu_url:=udp://:20101@` and waits for
`/mavros/state` to report `connected: true`. This ordering avoids waiting for
a topic that the official startup script does not create. MAVROS output is
saved as `/tmp/tcei_sim_environment/mavros.out`.

The startup helper does not submit a mission. The official `sim_env_start.sh`
may open its own legacy LLM terminal while initializing the graph; the formal
trial helper removes stale mission processes before starting the one argv-based
mission for that trial.

Use `run_formal_trial.sh` for one non-interactive official trial:

    bash ./run_formal_trial.sh red

It checks ROS/MAVROS/LLM/object/planner readiness, takes an exclusive trial
lock, removes stale `mission_once.py` processes, starts the observer, then runs
exactly:

    python3 mission_once.py "<natural-language task>"

The observer has two independent windows: `--pre-mission-timeout` waits for the
first `/mission_command`, while `--mission-timeout` starts only after that
message and waits for `/mission_result`. The formal script keeps one trial
lock until the observer and `mission_once.py` have both ended. It does not
restart ROS/SITL/RflySim.
