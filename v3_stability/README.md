# V3 稳定性与恢复修复（2026-10-06）

本目录记录 2026-10-06 这一轮工作的**实际部署产物**与验证证据。这一轮没有引入新的算法思路，
做的是两件更基础的事：

1. **修复 `hit_balloon` 阶段的恢复死锁** —— 这是一个稳定复现、每局直接损失 30 分的故障。
2. **改善 ArUco（二维码）识别节点的健壮性** —— 消除"识别结果被调试绘图吞掉"的结构性缺陷。

同时打通了**无头（不开网页桌面）启动仿真环境**的能力，这是后续所有自动化实验的前提。

---

## 一、恢复死锁修复（主要成果）

### 故障现象

在 `hit_balloon` 阶段，`VisualServo` 丢失目标后以 `yaw_rate=0.30` 原地搜索，
横向漂移到墙边 `y=3.00`（正好等于安全边界 `y_max=3.0`）。`SafetyRecovery` 随即进入
`RECOVERING`，然后**再也出不来**：

```
[SafetyRecovery] ENTER DRONE OUT OF BOUNDARY
[SafetyRecovery] current position = (5.30, 3.00, 0.95)
[SafetyRecovery] recovery target   = (5.30, 2.80, 0.95)
... 此后恢复输出一直覆盖上层控制指令 ...
[checkArrival] made no progress for 20.0s at target (0.0, 0.0, 0.5)
=> 卡到 300 s 超时，boundary_recovered=false
```

历史记录中 `20261001T161850_d96357` 与 `20261005T131925_aaf4d9` 两局是**同一个签名**，
即这不是偶发。

### 根因

`mavros_cnt.cpp` 中恢复目标点的 clamp 和恢复完成的确认条件**用的是同一个 margin**：

| 环节 | 表达式 | 数值 |
|---|---|---|
| 恢复目标点 | `y_max - recovery_margin` | `3.00 - 0.20 = 2.80` |
| 确认条件 `isWithinInnerBoundary()` | `y <= y_max - recovery_margin` | `y <= 2.80` |

**恢复目标点正好压在内边界上**。位置保持必然存在稳态误差，实测 `y` 始终略高于 2.80，
确认计时器每个周期被重置（日志中的 `confirmation reset`），飞行器被持续指挥去一个
它永远无法被确认到达的点。

### 修复方式

采用 `v1_safety_recovery/` 中**已经写好但从未部署**的版本，把两个 margin 解耦：

```xml
<param name="safety/recovery_target_margin" value="0.30" type="double"/>
<param name="safety/release_margin"        value="0.15" type="double"/>
<param name="safety/recovery_confirm_time" value="0.50" type="double"/>
```

- `recovery_target_margin`（0.30）决定恢复目标点位置
- `release_margin`（0.15）决定恢复完成门限
- 因为 `0.30 > 0.15`，目标点落在确认边界**内部**，确认能够正常锁存

代码侧另有校验：`target_margin` 必须大于 `release_margin`，且两倍 `target_margin`
不得大于任一轴的边界宽度，否则启动即 `ROS_FATAL` 拒绝运行。

### 部署内容

| 文件 | 说明 |
|---|---|
| `safety_recovery/llm_mission.launch` | 已打补丁的实际部署版本（安全参数解耦） |
| `v1_safety_recovery/src/mission_pkg/src/mavros_cnt.cpp` | 仓库中已有的修复版 C++（服务器现为该版本） |
| `v1_safety_recovery/src/mission_pkg/include/mavros_cnt.h` | 对应头文件 |
| `tools/patch_launch_safety.py` | 字节级补丁脚本（见下方"踩坑"） |

部署后节点启动日志确认生效：

```
[SafetyRecovery] target_margin=0.30 m release_margin=0.15 m confirm_time=0.50 s
```

> 注意：这几个参数在节点**构造时读取一次**，没有 dynamic_reconfigure。
> 修改边界参数必须重启 `llm_mission_node`。

---

## 二、越界验证（关键证据）

### 为什么需要专门构造越界

自然触发依赖 `VisualServo` 恰好把飞机漂到边界上，**不可控、不能保证复现**。
为了可靠验证"恢复分支能正常工作"，必须主动制造一次越界。

### 构造方式

不伪造遥测、不改源码，只把测试 launch 的 `safety/y_max` 从 `3.0` 收紧到 `1.5`
（见 `tools/make_boundary_test.py`）。这个值经过设计：

- 所有正常航点的 `y` 最大值为 **1.0**（气球 A 区目标点），因此航点仍在边界内、**目标保持可达**
- 但气球阶段的过冲会真的越过 `y = 1.5`

若边界收得比 1.0 还低（例如 0.7），目标点本身就在界外，会退化成持续振荡，无法用于验证。

### 验证结果

测试局 `20261006T140646_d12b94`，一次任务内**连续三次**被推出边界：

| 次数 | 越界位置 | 恢复耗时 |
|---|---|---|
| 1 | y = 1.51 | 4.920 s |
| 2 | y = 1.51 | 2.520 s |
| 3 | y = 1.53 | 2.000 s |

- 确认重置次数：**0**（旧代码为每周期重置）
- `boundary_recovered = true`
- `mission_success = true`，总耗时 142.7 s，**六个阶段全部 success**

即：**在一次被故意三次推出边界的任务里，飞行器全部自行恢复并完整跑完流程。**
旧代码在此必然卡到 300 s 超时，损失气球 25 分 + 降落 5 分。

验证判读脚本：`tools/check_recovery.py`。

> 验证完成后 `safety/y_max` 已还原为 `3.0`。测试用 launch
> `llm_mission_boundarytest.launch` 未被任何启动流程引用。

---

## 三、ArUco 节点健壮性修复

### 改动（`aruco/aruco_detect_node.py`，原文件存为 `.original`）

1. **把 `id_pub.publish()` 提到所有调试绘制 / `cv2.imshow` 之前**
   —— 这是真正有意义的修复。原代码中发布识别结果排在 debug 绘制之后，
   调试路径出任何问题都会**连带吞掉真实识别结果**。
2. 给绘制 / `imshow` / 存取图加 `try/except`，使它们成为"尽力而为"、不再影响识别主流程。
3. 增加 `INTER_CUBIC` 2× 上采样 + `CORNER_REFINE_SUBPIX` 亚像素角点精化。

### 证据强度（请如实理解）

- **离线 A/B 测试**（`tools/offline_aruco_ab.py`，按真实几何：0.15 m 码、
  640×480、90° FOV，即视野内 34–48 px）显示：**默认参数与新参数均为 24/24 全中**。
  因此**预处理是稳健性改进，并非失败根因的修复**。
- **上机结果**：ArUco 识别耗时由 `0.603 s` 改善至 `0.095 s`。

### 两种失败模式的定因结论

通过 5 局有完整观测的日志做取证，确认存在**两种不同**的失败：

| 模式 | 日志特征 | 判定 |
|---|---|---|
| A：回调卡死 | 20 s 内 **0 条** `Searching...`；订阅从 publisher 侧确认存活满 20.002 s；节点 stdout/stderr 全静默 | 回调未返回 |
| B：图像正常、码解不出 | **10 条** `Searching...`，各带 2–5 个被拒候选 | 检测质量不足 |

需要明确的是：**模式 A 的成因仍未确定**，本次修复并未针对它做验证。

另有一个曾被怀疑、但已被**实测证伪**的假设：`cv2.imshow` 在坏 X 环境下崩溃。
实测 X server 以 `-ac` 启动不需要认证，`imshow` 工作正常，历史日志中亦无任何
traceback 或 X/Gtk/Qt 报错。

---

## 四、无头启动仿真环境

`sim_env_start.sh` 通过 `xterm` 拉起全部节点，而 `start_sim_environment.sh`
会给子进程设置干净的 `HOME`，导致 xterm 找不到 `~/.Xauthority` 而立即退出。

解决方式：显式传递显示环境变量。

```bash
export DISPLAY=:20
export XAUTHORITY=/home/ubuntu/.Xauthority
```

之后 7 个 xterm 全部存活、ROS 图完整，**可全程通过 SSH 非交互启动与测试，无需网页桌面**。

---

## 五、踩坑记录（重要，避免重复踩）

1. **launch 文件不可经 shell `cat >` 往返传输**。
   该文件是 UTF-8 + CRLF，Windows 管道会把中文注释重新编码为非法字节，
   导致 roslaunch 报 `Invalid roslaunch XML syntax ... line 2, column 9`，
   `llm_mission_node` 直接起不来。请使用字节级补丁脚本 `tools/patch_launch_safety.py`。
   处理原则：读到该错误后**先还原备份，再重做**，不要在坏文件上继续叠加改动。

2. **本机 SSH 通道较脆弱**，表现为三种故障：
   SFTP 间歇性 `ENOENT`、Windows 控制台 GBK 编码崩溃、SSH banner 掉线。
   现已一并处理：改用 base64 经 stdin 传输、输出统一 `utf-8/replace`、连接加入重试。

3. **`pkill -f <脚本名>` 会匹配到自身的 SSH 命令行并自杀**。
   应改为按 PID 精确 kill，或使用 `[x]ruco` 之类的字符类规避。

4. **提交安全**：`.scratch/` 内含服务器口令，已在 `.gitignore` 中排除；
   `tools/srvctl.py` 的口令改为从环境变量读取。

---

## 六、目录结构

```
v3_stability/
├── README.md                     # 本文件
├── safety_recovery/
│   └── llm_mission.launch        # 已部署的安全参数解耦版本
├── aruco/
│   ├── aruco_detect_node.py      # 已部署的修复版
│   └── aruco_detect_node.py.original   # 修复前原版（回滚用）
├── tools/
│   ├── patch_launch_safety.py    # 字节级安全参数补丁
│   ├── make_boundary_test.py     # 生成越界测试 launch
│   ├── check_recovery.py         # 恢复流程判读
│   ├── aruco_capture.py          # 下视相机取帧（只读观测）
│   ├── offline_aruco_ab.py       # ArUco 参数离线 A/B
│   └── srvctl.py                 # 服务器控制（口令走环境变量）
└── reports/                      # 本轮实验记录
```

---

## 七、状态与后续

**已生效（服务器）**：`mavros_cnt.cpp`/`.h`（V1 修复版）、`llm_mission.launch`（安全参数解耦）、
`aruco_detect_node.py`（健壮性修复）、`mission_pkg` 已重新编译。

**已还原**：`safety/y_max` 回到 `3.0`。

**尚未做（等待决策）**：
- ArUco 修复需要 3–5 局/色 的重复实验才能给出可靠性结论（故障本身是间歇性的）
- `v2_1_ego_velocity` 的 A3/A4 档位补测（影响用时加分项）
- 观察点后固定延时、返框后两次 body GoTo 合并等**用时可优化点**
