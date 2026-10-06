# Astra 交接提示词：修复 ArUco（二维码）识别不稳定问题

> **使用方式**：把下面 `=====` 之间的全部内容整段复制发给 Astra。
> 如果你和 Astra 的会话已有上下文，仍然建议整段发送——其中包含它无法自行推断的实测数据。

---

```
===== 从这里开始复制 =====

# 任务：修复无人机二维码（ArUco）识别不稳定问题

你在一个真实的比赛项目上继续工作。**先读完这份提示词，再动手。**
不要凭常识推测本项目的行为——下面所有数字都是实测得到的，其中若干条与直觉相反。
上一轮有人（就是我）因为跳过实测、用合成数据下了结论，部署了一个**负优化**，
浪费了一轮完整实验。请避免重复这个错误。

---

## 〇、你有完全授权

你是来接活的，不是来咨询的。**以下事情直接做，不要问、不要等确认、不要只给建议**：

- SSH 登录服务器、读写其中文件
- 修改 `/home/ubuntu/catkin_ws/src/` 下的源码（**改前必须备份**）
- 重启任何 ROS 节点、终止卡住的进程、清理 `/tmp` 下的锁
- 实际驱动仿真跑正式试验（每局 50–300 秒，会真实消耗机时，这是被允许的成本）
- 编译：`cd /home/ubuntu/catkin_ws && catkin_make --pkg mission_pkg`

**唯一的例外**：不要改动比赛规则禁止项，不要推送到远端仓库，不要删除实验数据。

如果你发现自己在写"建议你……"、"可以先试试……"、"我认为应该……"——
停。你被要求的是**执行并报告结果**，不是提供选项清单。

**同时：不要假装完成。** 如果某步失败，报告失败和原始报错；不要用"应该可以了"糊过去。

---

## 一、环境访问

### 1.1 连接

```
Host: 120.209.70.195
Port: 30316
User: root
Password: <在此处粘贴项目负责人提供的口令>
         （口令不写入仓库。完整可直接复制的版本在 .scratch/astra-handoff-aruco-FULL.md，
           该目录已被 .gitignore 排除）
```

**注意**：这个口令是明文给的，用完**不要**写进任何会提交到 git 的文件
（仓库根目录的 `AGENTS.md` 已明确说明凭据不落库）。若需要脚本化访问，
用环境变量 `TCEI_PASSWORD`。

### 1.2 推荐工具（已在仓库里，直接用）

仓库路径 `D:\CICC-drone-attack`（Windows）。工具在 `v3_stability/tools/`：

```bash
# 远程执行命令
python v3_stability/tools/srvctl.py sh "你的命令"

# 上传本地文件到服务器（base64 管道，避免编码问题）
python v3_stability/tools/srvctl.py put 本地路径 远程路径

# 从服务器取文件
python v3_stability/tools/srvctl.py get 远程路径 本地路径
```

**Windows / Git Bash 必须加 `MSYS_NO_PATHCONV=1` 前缀**，否则远程路径
`/home/...` 会被 Git Bash 改写成 `D:/Git/home/...` 而失败：

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh "ls /home/ubuntu"
```

`srvctl.py` 已内置 SSH 重试（本机 banner 会偶发掉线）、UTF-8 输出、
base64 上传。**不要**改用裸 `scp` 或自己写 paramiko——本机 SFTP 会返回假的
"file not found"，SSH 会间歇性掉 banner，这些坑已经踩过了。

### 1.3 关键路径

| 路径 | 说明 |
|---|---|
| `/home/ubuntu/catkin_ws/` | **实际运行**的 ROS 工作区（注意：不是 git 仓库） |
| `.../src/mission_pkg/scripts/aruco_detect_node.py` | ArUco 节点，**Python，改完直接重启即可，无需编译** |
| `.../src/mission_pkg/launch/aruco_detect.launch` | ArUco 节点启动参数 |
| `.../src/mission_pkg/launch/llm_mission.launch` | 任务参数（航点、安全边界、优化参数） |
| `.../src/mission_pkg/src/mavros_cnt.cpp` | 安全恢复（**C++，改了必须重新编译**） |
| `/home/ubuntu/model/mission_once.py` | 大模型入口（须用 `/opt/conda/envs/demo/bin/python3`） |
| `/home/ubuntu/tcei_baseline_tools/` | 试验编排与结果目录 |
| `.../results/baseline_runs.csv` | 全部正式试验的汇总表 |

---

## 二、启动环境（无头，不需要网页桌面）

```bash
export DISPLAY=:20
export XAUTHORITY=/home/ubuntu/.Xauthority     # ← 缺这行 xterm 会全部秒退，环境起不来
cd /home/ubuntu/tcei_baseline_tools

# 若上次异常退出，先清残留锁（确认其中 PID 已死）
rm -rf /tmp/tcei_sim_environment.lock /tmp/tcei_formal_trial.lock

setsid nohup bash ./start_sim_environment.sh > /tmp/sim_start.log 2>&1 < /dev/null &
# 轮询 /tmp/sim_start.log 直到出现 environment_started=1（约 2–4 分钟）
```

### 验证环境就绪（**必须逐项确认，不要假设**）

```bash
set +u; source /opt/ros/noetic/setup.bash; source /home/ubuntu/catkin_ws/devel/setup.bash; set -u
rosnode list | grep -E "llm_mission|aruco_detect|ego_planner"   # 三个都应在
timeout 6 rostopic hz /rflysim/sensor2/img_rgb | grep average    # 应约 10 Hz
timeout 8 rostopic echo -n1 /mavros/state | grep -E "connected|mode"  # connected: True
```

### 跑一局正式试验

```bash
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
cd /home/ubuntu/tcei_baseline_tools
setsid nohup bash ./run_formal_trial.sh red > /tmp/trial.log 2>&1 < /dev/null &
# 完成判据：锁目录 /tmp/tcei_formal_trial.lock 消失
# 结果：results/formal_trials/<时间戳>_red_A0/observer.out（含 mission_success / failure_stage）
# 汇总：results/baseline_runs.csv 末行
```

**注意**：`run_formal_trial.sh` 用的是 `mission_once.py` 走大模型生成指令。
大模型**偶发**返回非法输出（没有 `command` 代码块），此时试验会在 20 秒内结束、
`mission_result` 缺失。**这不是算法故障，重跑即可**，但在报告里要分开统计。

---

## 三、问题是什么（已确证，不要重新推导）

### 3.1 分值影响

二维码识别 = **15 分，全有或全无**。失败一次直接损失 15 分，
并且后续「逆序穿框 15 分 + 击破气球 25 分 + 返航降落 5 分」全部无法进行——
**单次失败实际损失可能高达 60 分**。这是当前最重要的不稳定点。

### 3.2 失败现象（有直接证据，2026-10-06 试验 `20261006T151426_red_A0`）

该局 58.7 秒失败，`failure_stage=detect_aruco`。ArUco 节点自身日志：

```
15:15:26.402  Subscribed to /rflysim/sensor2/img_rgb
15:15:26.403  >>> Detection ENABLED <<<
15:15:26.494  Searching... no marker found (rejected: 2)   ← 整个 20 秒窗口只有这 1 条
   ... 19.9 秒完全没有任何输出 ...
15:15:46.402  Unsubscribed (saving CPU)
15:15:46.403  >>> Detection DISABLED <<<
```

**三条关键事实**：

1. `Searching...` 用的是 `loginfo_throttle(2.0)`，20 秒窗口**正常应产生约 10 条**，
   实际只有 **1 条**。
2. 同一时段，一个独立的采集节点收到了 **877 帧**（约 10 Hz）——
   **图像供给完全正常**。
3. 同一窗口的**真实图像回放**能稳定检出二维码 ID 35（帧 72–83）。

**结论：图像到达正常，但检测节点的回调没有被调度。这是首要故障（记为「模式 A」）。**

### 3.3 已排除的原因（**不要再去验证这些，会浪费时间**）

| 曾被怀疑 | 实测结论 |
|---|---|
| `cv2.imshow` 在坏 X 环境下崩溃 | **证伪**。X server 用 `-ac` 启动不需要认证，`imshow` 正常；历史日志无任何 traceback / X / Gtk / Qt 报错 |
| 二维码太小 | **证伪**。实测码宽约 **180 px**（640×480 画面），远高于识别阈值 |
| 用错 ArUco 字典 | **证伪**。字典 16 = `DICT_ARUCO_ORIGINAL`，与配置一致 |
| `max_vel` 档位（A0/A1/A2）影响成功率 | **无相关性** |

### 3.4 检测参数：已有实测结论，且与直觉相反

对 **84 帧真实捕捉帧**回放，评估**真实 ArUco 生效窗口**（帧 62–82，共 21 帧）：

| 配置 | 窗口命中 | 备注 |
|---|---:|---|
| 官方默认（1x 上采样，无角点精化） | 11/21 | 基线 |
| 2x 上采样 + subpix | **6/21** | **负优化——上一轮误部署，已回退** |
| CLAHE（1x，无精化） | 18/21 | 只加 CLAHE 就大幅改善 |
| **CLAHE + 3x + subpix** | **21/21** | 当前推荐配置 |
| 3x + subpix（无 CLAHE） | 9/21 | 上采样单独**无益** |
| CLAHE + 3x（无 subpix） | 21/21 | subpix 贡献可忽略 |

**真正起作用的是 CLAHE 直方图均衡。上采样和角点精化都不是关键，单独上采样还会变差。**

---

## 四、当前代码状态（你的起点）

服务器上 `aruco_detect_node.py` 目前是**上一轮的负优化版本**（md5 `616a965f`，
即 2x+subpix）。**不要以它为基线。**

以仓库中 `v3_stability/aruco/aruco_detect_node.py` 为起点，它已包含：

1. **CLAHE + 3x + subpix**，三项都是 ROS 参数（`~use_clahe` / `~upscale` / `~use_subpix`），
   可独立开关做对照实验
2. **`id_pub.publish()` 提到所有调试绘制之前**
   —— 原版把发布排在 debug 绘制之后，调试路径出任何问题都会**连带吞掉真实识别结果**
3. **`debug_display` 默认 `False`** —— 交互窗口默认关闭（针对假设 1）
4. **不节流的回调计数器** —— 每秒输出 `callbacks/s=N`，把"回调停摆"从推断变成直接测量

版本谱系：
- `v3_stability/aruco/aruco_detect_node.py.original` —— 官方原版（md5 `e9def27d`）
- `v3_stability/aruco/aruco_detect_node.regression_2x_subpix.py` —— 负优化版本（**反面教材**）
- `v3_stability/aruco/aruco_detect_node.py` —— 当前推荐起点

**先把它部署上去**，然后开始下面的实验：

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
  v3_stability/aruco/aruco_detect_node.py \
  /home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py
# 备份当前版本
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  "cp /home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py /tmp/aruco_node.bak_\$(date +%s)"

# 重启 ArUco 节点（注意：pkill -f 会匹配到你自己，用字符类规避）
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh '
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
PID=$(pgrep -f "[a]ruco_detect_node.py" | head -1)
[ -n "$PID" ] && kill $PID
sleep 2
set +u; source /opt/ros/noetic/setup.bash; source /home/ubuntu/catkin_ws/devel/setup.bash; set -u
setsid nohup roslaunch mission_pkg aruco_detect.launch > /tmp/aruco_relaunch.out 2>&1 < /dev/null &
sleep 10
rosnode list | grep aruco'
```

---

## 五、你要做的事（按顺序，每步都要产出证据）

### 步骤 1：确认回调停摆，并量化（**先测量，不要先改**）

部署 v3 版后，用采集工具记录**每局的回调速率**。工具在
`v3_stability/tools/capture_mission_frames.sh`（会同时抓取真实相机帧）。

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
  v3_stability/tools/aruco_capture.py /tmp/aruco_capture.py
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
  v3_stability/tools/capture_mission_frames.sh /tmp/capture_mission_frames.sh
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  "setsid nohup bash /tmp/capture_mission_frames.sh > /tmp/capture_run.log 2>&1 < /dev/null & echo started"
```

**产出**：每局 ArUco 窗口内 `callbacks/s` 的实测值，以及窗口内真实帧数。
写进报告：停摆发生时回调速率是多少，正常时应为多少。

**注意坑**：早期版本的采集脚本有竞态——会在试验**创建锁之前**就去判断锁是否存在，
导致只捕获 3 秒就停止；也可能被**上一次残留的锁**骗过而根本不启动试验。
现版本已修复（先清理死锁 → 启动试验 → 等锁出现 → 等锁消失），
但请**核对捕获到的帧数**是否覆盖整个任务（约 80+ 帧），异常就重来。

### 步骤 2：验证假设 1 —— 关闭交互显示窗口

`sim_env_start.sh` 以 `show_debug:=true` 启动，**显示调用与订阅回调在同一个线程**。

- 实验组：`debug_display=false`（v3 默认），但仍发布 `/aruco/debug_image` 话题
  （满足比赛「必须有感知结果可视化」要求）
- 对照组：`debug_display=true`

各跑 **3–5 局**，比较：ArUco 阶段成功率、窗口内回调速率。

**不要只跑一局就下结论。** 这个故障是间歇性的，单局不构成证据。

### 步骤 3：若假设 1 不成立，验证假设 2 —— 队列饥饿

把 `_subscribe()` 里的 `queue_size=1` 提到 5–10，重复步骤 2 的对照实验。
原理：解码耗时若超过帧间隔，`queue_size=1` 会让订阅端线程饥饿。

### 步骤 4：采样与耗时优化（次要，但顺手做）

- 现在的策略是「最快命中即退出」。若命中不稳定，考虑**连续 2 帧一致才发布**，
  代价是延迟略增，收益是抗单帧误检。
- 检测耗时本身也影响总用时（时间分最高 10 分）。记录每局的 ArUco 阶段耗时。

### 步骤 5：回归验证

改动稳定后，**红/紫/蓝各跑至少 2 局**，确认没有引入新的失败模式。
写入 `results/baseline_runs.csv` 的是自动的，但你需要在报告中汇总。

---

## 六、交付物（缺一不可）

1. **代码改动**：部署到服务器，并在仓库 `v3_stability/aruco/` 留一份当前版本
2. **实测报告**：写到 `v3_stability/reports/aruco_fix_<日期>.md`，必须包含：
   - 每局试验的**原始路径**（`results/formal_trials/<dir>/`）
   - 样本数与对照组：如「关闭显示窗口后 5 局中 5 局识别成功，
     此前 5 局中 2 局失败」——**要数字，不要形容词**
   - ArUco 窗口内 `callbacks/s` 的前后对比
   - **反例**：哪些情况下仍会失败
   - 回滚命令
3. **一句话结论**：修复是否有效，依据是什么，适用范围（哪种颜色/哪种条件）

---

## 七、报告纪律（重要）

**禁止**："应该可以"、"看起来正常"、"理论上没问题"、"建议尝试"。

**要求**：给出数字、样本数、原始日志路径，并**主动说明反例**。

**如果你发现自己只跑了一局**、或者**只做了代码修改没有上机验证**——
那不算完成，继续做。

**如果连续 3 次实验都指向同一结论**，就可以停止探索、写成报告。
不要无限尝试新假设——本项目的正确做法是"测量 → 改动 → 对照实验 → 收敛"。

---

## 八、遇到问题时的参考

仓库根目录 `AGENTS.md` 有完整的：
- 环境启动细节与原理
- 已排除的错误结论清单（**能帮你省下大量时间**）
- 已知陷阱（launch 文件编码、pkill 自杀、锁残留、SSH 不稳定等）
- 目录约定与报告规范

**开工前请先读它。** 里面记录的坑，每一个都已经真实踩过。

现在开始。先部署 v3 版本、启动环境、验证就绪，然后执行步骤 1。

===== 复制到这里结束 =====
```

---

## 附：本提示词的设计意图（给你，不用发给 Astra）

针对你提到的三个毛病，做了这些针对性设计：

**防懒惰**
- 步骤 1 明确要求"**先测量，不要先改**"，堵住"直接改代码然后宣布修好"
- 每个步骤都有**数字化的产出要求**（callbacks/s 具体值、帧数、局数）
- 交付物清单要求原始路径与反例，让"含糊收尾"无法通过
- 明确"只跑一局不算完成"

**防胆怯**
- 开头就给了**完整授权清单**并显式说明"不要问、不要等确认"
- 点名了它可能写出的逃避句式（"建议你……"、"可以先试试……"），并当场否定
- 口令、路径、命令都给全，不留"需要额外确认"的口子

**防不读上下文**
- 把**实测数据直接内嵌**（84 帧回放表、失败日志时间线），
  它不读 `AGENTS.md` 也能拿到关键事实
- 单列"已排除的原因"表，明确写着**不要再去验证**
- 明确指出起点是 `v3_stability/` 而非官方原版，避免从零重来
- 陷阱清单内联在提示词里（pkill 自杀、锁残留、MSYS 路径转换），不依赖它去翻文件

**一处诚实说明**：提示词里我明确写了"上一轮部署过一个负优化"。
这是真实情况，写进去有两个作用——让 Astra 知道"合成数据下结论"的代价，
以及提醒它**不要盲目信任现有代码**。如果这让你在交接时不便，可以删掉那两处
（§3.4 表格里的"负优化"标注、§四的"不要以它为基线"），但保留实测数据表——
那张表是它最需要的、无法自行推断的信息。
