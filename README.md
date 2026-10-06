# TCEI 无人机搜索打击

本仓库保存比赛原始工作空间、各轮改动和真实仿真试验记录。实际运行的 ROS 工作空间在服务器 `/home/ubuntu/catkin_ws/`；仓库中的版本文件不会自动部署。当前 ArUco 实测结果、限制和回滚命令见 [V3 试验报告](v3_stability/reports/aruco_fix_20261006.md)。协作与安全约束见 [AGENTS.md](AGENTS.md)。

## 文件索引

| 路径 | 用途 |
|---|---|
| `打击.pdf` | 比赛赛题原文。 |
| `AGENTS.md` | 服务器环境、已排除的结论、改动与试验纪律。 |
| `docs/` | 早期云端测试报告和 ArUco 交接记录；当前结果以 V3 试验报告为准。 |
| `official_baseline/catkin_ws/` | 官方 ROS 工作空间快照，供对照和回滚；其中的第三方源码按原目录保留。 |
| `baseline_tools/start_sim_environment.sh` | 启动 SITL、仿真环境并检查 ROS、里程计和 MAVROS 就绪状态；一套环境只启动一次。 |
| `baseline_tools/run_formal_trial.sh` | 按红、紫、蓝颜色运行一局官方自然语言任务，串行加锁并保存结果。 |
| `baseline_tools/run_baseline.py` | 订阅任务与遥测话题，生成 JSONL、阶段结果和汇总 CSV。 |
| `baseline_tools/results/` | 历史试验日志、遥测、CSV 与离线比较结果。 |
| `v1_safety_recovery/src/mission_pkg/` | 安全边界恢复的 C++ 与 launch 修改版。 |
| `v1_safety_recovery/patches/`、`restore_safety_recovery_v1.0.ps1` | V1 差异补丁与本地恢复脚本；验证记录在同目录的 `reports/`。 |
| `v2_1_ego_velocity/configs/A0–A4/` | Ego-Planner 速度档位配置；`experiments/`、`reports/` 保存试验和分析。 |
| `v2_1_ego_velocity/restore_v2_1_configs.ps1` | 恢复 V2.1 规划器配置；`backups/` 保存原文件与校验值。 |
| `v2_time_optimization/working_source/` | 时间优化工作源码；`patches/`、`backups/`、`reports/` 分别存差异、回滚文件和验证。 |
| `v3_stability/aruco/aruco_detect_node.py` | 当前 ArUco 节点版本：CLAHE 检测、可配置队列与独立回调率日志。 |
| `v3_stability/aruco/aruco_detect_node.py.original`、`aruco_detect_node.regression_2x_subpix.py` | 官方原版与已证实负优化的历史版本，供比较。 |
| `v3_stability/safety_recovery/llm_mission.launch` | 已验证的安全恢复参数版本。 |
| `v3_stability/reports/` | V3 的原始证据与结论；详细历史见 [V3 README](v3_stability/README.md)。 |
| `.scratch/` | 本地临时文件和凭据，已被 Git 忽略，禁止提交。 |

## 工具速查

下表文件均位于 `v3_stability/tools/`。

| 文件 | 做什么 |
|---|---|
| `v3_stability/tools/srvctl.py` | 使用环境变量中的 SSH 凭据执行 `sh`、上传 `put`、下载 `get`、列目录 `ls`；自动重试连接。 |
| `aruco_capture.py` | 订阅真实下视相机，每隔指定秒数保存一帧 PNG，并记录收到的帧数。 |
| `capture_mission_frames.sh` | 在服务器上同步采集相机帧并运行一局**红色**正式任务；依赖已上传的 `/tmp/aruco_capture.py`。 |
| `aruco_window_eval.py` | 对真实采集帧的 ArUco 生效窗口比较检测参数；正式结论使用此脚本和正式试验记录。 |
| `replay_aruco.py` | 对真实帧回放更多候选参数；其中部分配置标签是历史名称。 |
| `offline_aruco_ab.py` | 合成图像快速检查；不能作为比赛性能结论。 |
| `patch_launch_safety.py` | 在服务器上按字节修改 `llm_mission.launch`，保留原编码与换行；运行前备份。 |
| `make_boundary_test.py` | 生成收紧 `y_max` 的越界验证 launch，不用于正式任务。 |
| `check_recovery.py` | 从恢复试验日志提取进入边界、恢复和确认事件。 |

## 常用操作

先按 [AGENTS.md](AGENTS.md) 设置本机 `TCEI_HOST`、`TCEI_PORT`、`TCEI_USER`、`TCEI_PASSWORD` 环境变量；口令只放在本机环境或 `.scratch/`。以下命令在仓库根目录执行。Git Bash 调用 `srvctl.py` 时加 `MSYS_NO_PATHCONV=1`；PowerShell 不需要。

```bash
# 连接与传文件
python v3_stability/tools/srvctl.py sh "pwd"
python v3_stability/tools/srvctl.py put v3_stability/tools/aruco_capture.py /tmp/aruco_capture.py
python v3_stability/tools/srvctl.py get /home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv .scratch/baseline_runs.csv

# 服务器环境只启动一次；先核对 /tmp/tcei_sim_environment.lock 中记录的进程
python v3_stability/tools/srvctl.py sh "export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; cd /home/ubuntu/tcei_baseline_tools; setsid nohup bash ./start_sim_environment.sh > /tmp/sim_start.log 2>&1 < /dev/null &"
python v3_stability/tools/srvctl.py sh "tail -n 20 /tmp/sim_start.log"

# 环境就绪后，串行运行一局；颜色可改为 purple 或 blue
python v3_stability/tools/srvctl.py sh "export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; cd /home/ubuntu/tcei_baseline_tools; setsid nohup bash ./run_formal_trial.sh red > /tmp/trial.log 2>&1 < /dev/null &"
python v3_stability/tools/srvctl.py sh "tail -n 3 /home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv"
```

正式结果在服务器的 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/`；运行前确认没有活跃的 `/tmp/tcei_formal_trial.lock`。需要采集红色任务的真实帧时，先用上面的 `put` 上传采集节点，再运行：

```bash
python v3_stability/tools/srvctl.py shf v3_stability/tools/capture_mission_frames.sh
python v3_stability/tools/aruco_window_eval.py <真实帧目录> --lo <窗口首帧> --hi <窗口末帧>
```

评估窗口需按该局的 ENABLED→DISABLED 日志和采集日志对齐；采集脚本每秒只保存一帧，正式成功率以试验结果为准。Python 源码改动后需重启对应 ROS 节点；C++ 改动后还需重新编译 `mission_pkg`。每次部署先备份服务器原文件，并在报告中记录校验值和回滚命令。
