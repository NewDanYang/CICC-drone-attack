# AGENTS.md — TCEI 无人机搜索打击项目协作指南

本文件写给在本仓库工作的 AI 编码代理。人类协作者也应阅读。
**开始任何工作前请完整读完本文件**——其中的"已排除的错误结论"能直接避免你重做数小时的无用功。

---

## 1. 项目是什么

TCEI（具身智能）无人机搜索打击赛题。无人机在 6×5×3 m 室内场景中，
通过**自然语言指令**驱动大模型生成行为树，完成六个阶段：

| 阶段 | 分值 | 说明 |
|---|---:|---|
| 起飞 | 5 | |
| 穿越方框 | 15 | |
| 识别二维码（ArUco） | 15 | **当前主要不稳定点** |
| 逆序穿越方框 | 15 | |
| 击破指定颜色气球 | 25 | |
| 返航降落 | 5 | |
| 创新路径规划 | 10 | 需技术文档与现场演示佐证 |
| 加分：九格多模态大模型目标识别 | 10 | |

**计分特性（决定了工作优先级）**：
- 每阶段**全有或全无**。一个阶段失败即该阶段分值归零。
- 总用时按名次映射 0–10 分：`10 - 10*(T-Tfast)/(Tslow-Tfast)`。
- **所以：先保成功率，再压缩时间。** 一次阶段失败（15–25 分）远大于时间优化的收益（≤10 分）。

---

## 2. 访问与运行环境

### 2.1 仿真服务器

```
Host: 120.209.70.195   Port: 30316   User: root
```

口令**不写入本文件**（本文件会进 git）。使用环境变量：

```bash
export TCEI_HOST=120.209.70.195
export TCEI_PORT=30316
export TCEI_USER=root
export TCEI_PASSWORD='<向项目负责人索取>'
```

`v3_stability/tools/srvctl.py` 是配套的 SSH 控制脚本（已内置重试、UTF-8 输出、字节安全上传）：

```bash
python v3_stability/tools/srvctl.py sh  "命令"        # 远程执行
python v3_stability/tools/srvctl.py put 本地 远程      # 上传（base64 管道）
python v3_stability/tools/srvctl.py get 远程 本地
```

**Windows 用户注意**：路径会被 Git Bash 转换，需加前缀
`MSYS_NO_PATHCONV=1`，否则远程路径会被改写成 `D:/Git/home/...` 而失败。

### 2.2 关键路径

| 路径 | 内容 |
|---|---|
| `/home/ubuntu/catkin_ws/` | **实际运行的** ROS 工作区（非 git 仓库） |
| `/home/ubuntu/catkin_ws/src/mission_pkg/` | 行为树、安全恢复、ArUco 节点 |
| `/home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py` | ArUco 节点（Python，**直接从源码运行，改完不需 catkin_make**） |
| `/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch` | 任务参数（安全边界、优化参数、航点） |
| `/home/ubuntu/catkin_ws/sim_env_start.sh` | 官方环境启动脚本（用 xterm 拉起各节点） |
| `/home/ubuntu/model/mission_once.py` | 大模型入口（Python 解释器须用 `/opt/conda/envs/demo/bin/python3`） |
| `/home/ubuntu/tcei_baseline_tools/` | 观测/编排工具与结果 |
| `/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv` | **所有正式试验的汇总记录** |

### 2.3 启动仿真环境（无头，无需网页桌面）

```bash
export DISPLAY=:20                      # X server 已在跑
export XAUTHORITY=/home/ubuntu/.Xauthority   # ← 缺这条 xterm 全部秒退
cd /home/ubuntu/tcei_baseline_tools
setsid nohup bash ./start_sim_environment.sh > /tmp/sim_start.log 2>&1 < /dev/null &
# 等待日志出现 environment_started=1（约 2–4 分钟）
```

**为什么必须显式设 `XAUTHORITY`**：`start_sim_environment.sh` 会给子进程
设置干净的 `HOME`，xterm 因此找不到 `~/.Xauthority` 而立即退出，导致
`sim_env_start.sh` 里所有节点起不来、ROS 图不完整。

### 2.4 跑一次正式试验

```bash
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
cd /home/ubuntu/tcei_baseline_tools
setsid nohup bash ./run_formal_trial.sh red > /tmp/trial.log 2>&1 < /dev/null &
```

- 参数：`red` / `purple` / `blue`
- 用锁目录 `/tmp/tcei_formal_trial.lock` 保证串行；**锁残留会让后续试验直接失败**
- 结果写入 `results/formal_trials/<时间戳>_<颜色>_<档位>/`
- 单局约 50–300 s

---

## 3. 必须遵守的工作纪律

### 3.1 证据优先，禁止"看起来修好了"

**血泪教训（真实发生过）**：曾用**合成图像**验证 ArUco 参数改进，得出"更优"的结论并部署；
后来用**真实捕捉帧**回放发现该改动实为**负优化**（命中 13 → 6），不得不回退。

因此：

1. **任何性能结论必须基于真实仿真数据**。合成数据只能用于探索，不能用于结论。
2. **单局成功不能证明修复有效**。本赛题故障多为间歇性，至少 **3–5 局**才能下判断。
3. **区分"环境故障"与"算法故障"**。见 §4.1。
4. 报告结论时必须写清：样本数、对照组、度量指标、以及**该结论不适用的范围**。

### 3.2 不要停下来问

你有明确授权做以下事，**直接做，事后报告**：

- 编辑 `catkin_ws/src/` 下的源码（**先备份**）
- 重启 `llm_mission_node`、`aruco_detect_node` 等节点
- 终止卡住的进程、清理 `/tmp` 下的锁与临时文件
- 运行正式试验（会实际驱动仿真）
- 编译：`cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg`（C++ 改动后必须）

**需要先问的只有**：修改比赛规则禁止项、删除他人数据、推送到远端仓库、改动安全边界默认值以外的系统配置。

### 3.3 每次改动必须可回滚

- 改动前 `cp 原文件 原文件.bak_<日期>`，并记录 md5
- 报告里给出**回滚命令**
- 不要在一份已经损坏的文件上继续叠加修改——先还原再重做

---

## 4. 已排除的错误结论（**不要重复验证**）

### 4.1 环境类

| 曾被怀疑的原因 | 实测结论 |
|---|---|
| `cv2.imshow` 在坏 X 环境下崩溃导致回调死掉 | **证伪**。X server 以 `-ac` 启动不需要认证，`imshow` 正常；历史日志无任何 traceback / X / Gtk / Qt 报错 |
| 二维码太小以致无法识别 | **证伪**。实测码宽约 **180 px**（640×480 画面），远高于阈值 |
| ArUco 用错字典 | **证伪**。字典为 16 = `DICT_ARUCO_ORIGINAL`，与配置一致 |
| `max_vel`（A0–A2）影响 ArUco 成功率 | **无证据支持**。失败与档位无相关性 |

### 4.2 ArUco 检测参数（基于 84 帧真实捕捉帧回放）

评估窗口取**真实 ArUco 生效区间**（帧 62–82，共 21 帧，对应 ENABLED→DISABLED）：

| 配置 | 窗口命中 | 说明 |
|---|---:|---|
| 官方默认（1x，无角点精化） | **11/21** | 基线 |
| 2x 上采样 + subpix | **6/21** | **负优化，已回退** |
| CLAHE（1x，无精化） | **18/21** | 仅加 CLAHE 即大幅改善 |
| **CLAHE + 3x + subpix** | **21/21** | 当前推荐 |
| 3x + subpix（无 CLAHE） | 9/21 | 上采样单独无益 |
| CLAHE + 3x（无 subpix） | 21/21 | subpix 贡献可忽略 |

**结论：真正起作用的是 CLAHE 直方图均衡，不是上采样，也不是角点精化。**
单独的 2x 上采样是负优化。

---

## 5. 当前主攻方向：ArUco 回调停摆

### 5.1 现象（有直接证据）

2026-10-06 试验 `20261006T151426_red_A0`（失败，58.7 s，`failure_stage=detect_aruco`）：

```
15:15:26.402  Subscribed to /rflysim/sensor2/img_rgb
15:15:26.403  >>> Detection ENABLED <<<
15:15:26.494  Searching... no marker found (rejected: 2)   ← 全窗口仅此 1 条
   ... 19.9 秒无任何输出 ...
15:15:46.402  Unsubscribed (saving CPU)
```

- `Searching...` 使用 `loginfo_throttle(2.0)`，正常 20 s 应产生约 **10 条**，实际 **1 条**
- 同时段独立采集节点收到 **877 帧**（约 10 Hz），**图像供给正常**
- 同窗口回放可稳定检出码 ID 35（帧 72–83）

**判定：图像到达正常，但检测节点的回调未被调度。这是当前首要故障。**

### 5.2 待验证假设（按优先级）

1. **`cv2.imshow` + `waitKey(1)` 阻塞同线程回调** —— `sim_env_start.sh` 以
   `show_debug:=true` 启动，importantly 显示调用与订阅回调在**同一线程**。
   *验证方式*：把交互窗口关掉（`debug_display:=false`，仅推 `/aruco/debug_image` 话题），
   跑 3–5 局看回调速率与成功率。
2. **`queue_size=1` 导致 RX 队列饥饿** —— 解码耗时 >100 ms 时可能丢帧甚至让
   订阅端线程饥饿。*验证方式*：提高 `queue_size` 观察回调计数变化。
3. **节点被同机其他进程挤占 CPU** —— 检查 `load average` 与节点 CPU 占用。

### 5.3 已部署的 v3 版本

`v3_stability/aruco/aruco_detect_node.py` 已包含：

- **CLAHE + 3x + subpix**（按 §4.2 实测选型，三项均为 ROS 参数，可单独关闭）
- **`id_pub.publish()` 提到所有调试绘制之前** —— 原版中发布排在 debug 之后，
  调试路径出任何问题都会连带吞掉真实识别结果
- **`debug_display` 默认 False** —— 交互窗口默认关闭（假设 1 的修复）
- **不节流的回调计数器** —— 每秒输出一次 `callbacks/s`，使 §5.1 的停摆
  从"推断"变成"直接测量"

**这是当前最佳版本的起点，请以它为基线继续，不要从官方原版重新开始。**

---

## 6. 已知陷阱清单

1. **launch 文件不可经 shell `cat >` 往返**。该文件是 UTF-8 + CRLF，Windows 管道会把
   中文注释重新编码为非法字节，导致 roslaunch 报
   `Invalid roslaunch XML syntax ... line 2, column 9`，节点直接起不来。
   请使用 `v3_stability/tools/patch_launch_safety.py` 这种**字节级**修改方式。

2. **`pkill -f <脚本名>` 会匹配到执行该命令的自身进程并自杀**，表现为
   exit code 127 且远程命令无输出。改为按 PID 精确 kill，或用字符类规避：
   `pgrep -f "[a]ruco_detect_node"`。

3. **锁残留**：`/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`
   残留会导致新试验静默失败。启动前检查，确认其中记录的 PID 已死再清理。

4. **SSH 通道不稳定**：本机会偶发 SSH banner 掉线、SFTP 返回假的 ENOENT、
   Windows 控制台 GBK 编码崩溃。请使用 `srvctl.py`（已内置重试、UTF-8 输出、
   base64 上传），**不要直接用 paramiko 默认配置或裸 `scp`**。

5. **`llm_mission.launch` 里同时含 V2 优化参数**（`optimization/*` 四行）。
   整体覆盖该文件会冲掉它们——**只做定点修改**。

6. **C++ 改动需重新编译**，Python 改动不需要。忘记编译是最常见的"改了没效果"原因。

7. **大模型 `mission_once.py` 偶发返回非法输出**（无 `command` 代码块），
   试验会在 20 s 内结束且 `mission_result` 缺失。这**不是**算法故障，
   重跑即可——但要在报告中区分开。

---

## 7. 目录约定

```
official_baseline/        官方原始快照，只读
baseline_tools/           观测工具与试验记录
v1_safety_recovery/       安全边界恢复（已部署并通过越界验证）
v2_1_ego_velocity/        Ego-Planner 速度档位实验（A0–A4）
v2_time_optimization/     时间优化审计与 patch 1
v3_stability/             当前工作目录：ArUco + 安全恢复部署产物
  ├── aruco/              ArUco 版本谱系（original / regression / 当前）
  ├── safety_recovery/    已部署的 launch
  ├── tools/              replay / capture / 判读 / SSH 控制
  └── reports/            验证证据
.scratch/                 本地临时区，**含凭据，已 gitignore，禁止提交**
```

---

## 8. 报告规范

每次有结果的试验，产出：

1. **原始证据路径**（日志、CSV、帧目录），不只是结论
2. **样本数与对照组**——"3 局中 2 局成功"而非"修复有效"
3. **明确区分**：算法改动 / 环境偶发 / 大模型输出异常
4. **回滚方式**
5. **结论的适用范围**——单色单档位的结论不要外推到全部

**禁止的表述**："应该可以"、"看起来正常"、"理论上没问题"。
**要求的表述**：给出数字、样本数、以及反例（哪些情况仍会失败）。

---

## 9. 多人协作（服务器是唯一共享资源）

仿真服务器是单实例、**全组共用**。两人同时跑正式试验会互相破坏对方的锁与数据。
当前的目录划分（见各自的交接文档 `docs/team-brief-*.md`）：

| 负责方向 | 拥有的目录（改前无需问，改后互相同步） |
|---|---|
| 稳定性（hit_balloon、ArUco 停摆） | `v1_safety_recovery/`、`v3_stability/aruco/`、`v3_stability/reports/` |
| 评分优化（多模态加分、创新规划、用时） | `v2_time_optimization/`、`v2_1_ego_velocity/`、新建的多模态/规划目录 |

**用服务器前**，检查是否有人正在用：

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'ls -d /tmp/tcei_formal_trial.lock 2>/dev/null; tail -1 /home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv'
```

若存在锁目录、或 CSV 最后一行时间戳在最近 10 分钟内，先在团队沟通渠道确认再动手，
不要直接清锁抢占。若服务器端口（30316）连接被拒绝，说明云主机实例已关机，这**不能**
用 SSH 解决，需要有 gpufree.cn 控制台权限的人去重新开机。

**Git 分支**：各自在自己的 feature 分支工作（见交接文档里指定的分支名），
改完发 PR 到 `main`，不要直接推 `main`。合并前互相过一遍对方有没有动到自己目录外的文件。

