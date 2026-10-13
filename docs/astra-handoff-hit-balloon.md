# Astra 交接提示词：继续解决 hit_balloon（击破气球）阶段失败

> **使用方式**：把下面 `=====` 之间的全部内容整段复制发给 Astra。
> 本提示词以 PR #2（`feature/hit-balloon-midterm`，已合入 `main`，中期报告
> `v3_stability/hit_balloon_midterm/reports/midterm_report_20261011.md`）为起点，
> 并内嵌了对该 PR 的复核结论——其中几条是 PR 报告本身没写的。

---

```
===== 从这里开始复制 =====

# 任务：让 hit_balloon（击破气球，25 分）在红/紫/蓝三色上稳定成功，并用客观证据证明

你在一个真实比赛项目上接手一项已经做了一半的工作。**先读完这份提示词，再动手。**
下面的数字和时间线都是从服务器证据目录和代码里核对出来的；有几条与上一轮报告的
口径不同，请以这里为准，并在发现矛盾时以服务器实测为最终依据。

---

## 〇、授权与纪律

**直接做、事后报告，不要停下来问**：SSH 登录服务器读写文件、修改
`/home/ubuntu/catkin_ws/src/` 下源码（**改前备份并记录 md5**）、重启节点、
终止卡住的进程、清理确认已死的锁、跑正式试验、`catkin_make --pkg mission_pkg`。

**需要先问的只有**：改比赛规则禁止项、改安全边界默认值（`safety/*`）、
删除别人的实验数据、推送到 `main`（应发 PR）。

**纪律**：
- 单局成功不是证据。故障是间歇性的，每个结论至少 3 局，并写清样本数与对照组。
- 写出"建议你……/可以试试……/应该可以了"时停下——你的任务是执行并给出数字。
- 不要假装完成。失败就报失败和原始报错。
- 先读仓库根目录 `AGENTS.md`（环境、已排除结论、已知陷阱、报告规范）。本文不重复的细节都在那里。

---

## 一、访问与同步

```bash
export TCEI_HOST=120.209.70.195 TCEI_PORT=30316 TCEI_USER=root
export TCEI_PASSWORD='<向项目负责人索取，不要写进任何会提交的文件>'
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh "echo OK"
```

- Windows / Git Bash 下所有 `srvctl.py` 调用都要加 `MSYS_NO_PATHCONV=1`。
- 端口连接被拒绝 = 云主机关机，SSH 解决不了，找有 gpufree.cn 控制台权限的人。
- **先 `git pull origin main`**，确认本地存在 `v3_stability/hit_balloon_midterm/`
  （PR #2 的产物）。本机 git 若连不上 github.com，PR #2 的文件已解出一份在
  `.scratch/pr2/src/`（文件名里的 `__` 代表目录分隔）。
- 新建分支：`git checkout -b fix/hit-balloon-v2`，完成后发 PR 到 `main`。

**服务器是全组共用的单实例。** 每次跑试验前执行：

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'ls -d /tmp/tcei_formal_trial.lock 2>/dev/null; ls -dt /home/ubuntu/hit_balloon_trials/* 2>/dev/null | head -2; tail -1 /home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv'
```

存在锁目录、或最近 10 分钟内有新试验目录 / CSV 行 → 有人在用，先去团队渠道确认，
**不要清锁抢占**。注意：队友的 `run_hit_regression.sh` **不拿共享锁**，
所以只看锁不够，还要看 `hit_balloon_trials/` 下的新目录。

---

## 二、现状（已核实，不要重新发现）

### 2.1 基线数据（2026-10-06，PR #2 之前）

14 局有效正式试验：ArUco 红 9/9、紫 2/2、蓝 2/2 全过；完整通过 4/14
（`20261006T150933` 红、`20261006T162450` 红、`20261006T181920` 紫、`20261006T182538` 蓝），
其余 10 局 `failure_stage=hit_balloon`。

**关键口径（之前没人点明）**：`baseline_tools/run_baseline.py:700` 判定
`hit_balloon_status=success` 的依据是日志里出现 `Sprint completed ... success`——
**这只说明冲刺执行完了，不说明气球破了。** 所以 4/14 是"冲刺完成率"，
不是击破率；10 局失败是"没完成冲刺"。

### 2.2 行为树结构（官方原版 `official_baseline/.../config/full_competition_red.xml`）

```xml
<GoTo goal="5.3;1.0;1.0" yaw="1.5708"/>            <!-- 红/蓝：朝 +y；紫：5.3;-1.0;1.0 yaw=-1.5708 -->
<ForceSuccess>
  <Timeout msec="50000">
    <Parallel success_count="1" failure_count="1">
      <TargetTracker object_name="red_balloon" confidence_threshold="0.8" .../>
      <VisualServo ... approach_area_threshold="0.08" forward_velocity="0.35"
                   sprint_velocity="1.5" sprint_time="1.2" />
    </Parallel>
  </Timeout>
</ForceSuccess>
<GoTo goal="0.0;0.0;0.5" yaw="0.0"/>  <Land/>
```

- **行为树由大模型生成**（`/home/ubuntu/model/mission_once.py`）。XML 端口参数
  （sprint_velocity 等）最终取决于大模型输出 / 提示词模板，而不是 launch 文件。
  改参数前先找到它们在生成链路中的真实来源。
- `ForceSuccess` 把超时和所有失败都吞成 SUCCESS，所以 `Mission result: SUCCESS`
  对击球毫无证明力。

### 2.3 PR #2 部署到服务器上的改动（2026-10-11，按时间）

| 时间 | 事件 | 证据目录（服务器 `/home/ubuntu/`） |
|---|---|---|
| 01:22–02:30 | 规划门控、返航转向、降落停稳；返航 2 局正常 | `landing_retest_20261011T012235/` |
| 02:59 | 冲刺居中门控 **V4** | `visual_sprint_alignment_v4_backup_20261011T025959` |
| **03:01** | **红球击破（操作员目视确认，全程唯一一次）** | `hit_balloon_trials/red_regression_20261011T030125` |
| 03:05 | 紫球失败 | `hit_balloon_trials/purple_regression_20261011T030532` |
| **03:14** | **偏航符号取反**（yaw_direction_v1） | `visual_yaw_direction_v1_backup_20261011T031447` |
| 03:16 / 03:40 | 紫球失败 ×2 | `purple_regression_20261011T031644`、`...T034032` |
| 04:00 | 累计限时搜索 v3（8 s） | `bounded_visual_search_v3_backup_20261011T040040` |
| 04:03 | 紫球失败，触发 `SafetyRecovery`，安全返航 | `purple_regression_20261011T040323` |

**由此得出、但 PR #2 报告没写的结论**：

1. **当前部署版本没有任何颜色的成功击破证据。** 唯一一次红球成功发生在偏航取反
   **之前**；取反之后红球没有再测过，蓝球从未独立测过，紫球 0/4。
   偏航取反到底是修复还是破坏，**目前未知**——这是第一个要回答的问题。
2. **仓库与服务器不一致**：仓库里是 `patch_visual_sprint_alignment_v3.py`，服务器部署的是 V4；
   `patch_bounded_visual_search_v3.py` 依赖 v1（脚本会报 "v1 not deployed"），但 v1 补丁不在仓库里。
   真实改动以各备份目录里的 `changes.diff` 为准。
3. **冲刺日志参数错位**：对齐补丁里的
   `ROS_INFO("... SPRINT! (sprint_vel=%.2f, time=%.1fs)", ratio*100, threshold*100, sprint_velocity_, sprint_time_)`
   只有 3 个占位符却传了 4 个参数——`sprint_vel=` 打出的是面积阈值，`time=` 打出的是速度。
   **PR #2 期间所有冲刺日志里的这两个数都不可信。**
4. **运行时参数可能没生效**：`run_hit_regression.sh` 用 `rosparam set /visual_servo/sprint_velocity 0.8`、
   `sprint_time 0.4` 等调参，但 VisualServo 是通过 BT 端口 `getInput<>()` 读参数的
   （限时搜索补丁就读 `getInput<double>("search_timeout")`）。这些 rosparam 可能对行为树
   **完全不起作用**，节点重启后也会丢失。需要核实，不要假设。
   另外：若 0.8 m/s × 0.4 s 真的生效，冲刺距离只有 **0.32 m**，而官方是 1.5 × 1.2 = 1.8 m。
   面积刚到 8% 时离气球多远，没人量过——这是一个值得测量的未命中假设。
5. `tools/analyze_hit_trial.py` 把 `"User observation: red balloon not popped."` 写死在代码里，
   而且只统计 `red_balloon`。不要直接用它分析别的局。

### 2.4 已排除 / 已解决（不要重复验证）

- 安全恢复死锁：已修复并验证（主动越界 3/3 恢复，`v3_stability/reports/boundary_proof_raw.txt`）。
  但要核对服务器上 `mavros_cnt.cpp` 的 md5 是否仍是 `edcd9397`（`.h` 是 `f6a6a2c8`）。
- ArUco：10-06 批次 13/13 通过。回调停摆问题**未知**，不是"已解决"（见 §5 步骤 6）。
- 目标类别筛选正确（日志里是 `purple_balloon`），不是类别错误。

---

## 三、目标与成功判据

**最终目标**：红、紫、蓝**各至少 3 局**正式试验（走 `run_formal_trial.sh`，拿共享锁、写 CSV），
在**客观击破判据**下击破率尽可能高，并且失败局仍然安全返航降落（保住 5 分）。

**"击破"必须有不依赖操作员、也不依赖 `SUCCESS` 的客观判据**。步骤 2 负责建立它。

---

## 四、执行步骤（按顺序，每步都要有产出）

### 步骤 1：盘点服务器实际状态（不改任何东西）

产出 `v3_stability/hit_balloon_v2/deployed_manifest_<日期>.md`，内容包括：
- 下列文件的 md5：`visual_servo.cpp`、`planning_control.cpp/.h`、`bt_ros.cpp`、`goto.cpp`、
  `mavros_cnt.cpp/.h`、`target_detector_base.cpp`、`target_tracker.cpp`、
  `aruco_detect_node.py`、`det_color.py`、`llm_mission.launch`、`devel/lib/mission_pkg/bt_ros`
  （`bt_ros` 二进制的修改时间必须晚于源码，否则就是"改了没编译"）
- 第 2.3 节每个备份目录的 `changes.diff`，**拷回仓库** `v3_stability/hit_balloon_v2/deployed_diffs/`
  ——补齐仓库里缺失的 V4 对齐补丁和 v1 限时搜索补丁
- 当前生效的击球 BT XML（找到 `mission_once.py` 是如何生成或选择 XML 的；
  取一份它最近真实下发的 XML）
- 第 2.3 节第 4 条的结论：`/visual_servo/*` rosparam 是否被代码读取（`grep -n "param\|getInput" visual_servo.cpp`）

### 步骤 2：建立客观击破判据，并修好冲刺日志

1. 先修 §2.3 第 3 条的 `ROS_INFO` 参数错位（字节级修改，保留 CRLF，备份，编译）。
   顺手在冲刺开始和结束时各打一行：当前位置、偏航、`err_x/err_y`、面积比、实际使用的
   `sprint_velocity/sprint_time`。
2. 找客观信号，按可靠性排序验证：
   - 仿真器是否发布气球模型状态（破裂 / 消失 / 被删除）？查 RflySim 场景配置与话题列表
   - 场景中三个气球的世界坐标（场景配置或 BT 注释里的区域位置），对比冲刺期间无人机里程计的
     **最近距离**：最近距离 < 气球半径 + 机体半径 → 判定为碰撞
   - 冲刺后目标在 `/objects` 中持续消失（只能作辅助，单独不足以判定，PR #2 已指出）
3. **校准判据**：用已知结果回放检验——`red_regression_20261011T030125` 必须判为击破；
   10-06 那 4 局"完整成功"各判为什么，如实记录（它们只证明冲刺完成）。
4. 写成脚本 `v3_stability/hit_balloon_v2/tools/judge_hit.py`：输入试验目录（bag/telemetry），
   输出 `hit=true/false/unknown` 及依据。三色通用，**不许写死结论文字**。

### 步骤 3：判定偏航符号（直接测量，不靠胜负）

这一步能用 1–2 局确定性地回答，**先于任何回归**做：
- 让无人机悬停在击球点、面向目标，用固定的小偏航角速度（例如 ±0.2 rad/s，各 2 s）分别给正、负指令，
  记录气球 `center_x` 的变化方向。由此得出：`err_x > 0` 时需要的 `yaw_rate` 符号。
- 对照 `visual_servo.cpp` 当前公式（取反后为 `yaw_rate = +(kp*err + kd*d_err)`），判断现在的符号对不对。
- 再用数据核对 PR #2 里"紫球误差 −218 px、偏航饱和在 +0.500"那一局：在当时的符号下，
  这个指令是在把目标往中心拉，还是往外推？
- 如果符号错误：执行 `visual_yaw_direction_v1_backup_20261011T031447/restore.sh` 回滚（会自动重新编译），
  并在报告里写明。
- 正确符号确定后，**跑红球 3 局**确认红球没有被打坏（与 03:01 那次成功形成对照）。

### 步骤 4：给已有失败局分类（先用旧数据，不急着跑新的）

数据源：10-06 批次的 10 局失败（`/home/ubuntu/tcei_baseline_tools/results/formal_trials/`）、
PR #2 的 4 局紫球和第一局红球、以及步骤 3 的新局。每局归入且只归入一类：

| 类 | 特征 |
|---|---|
| A 未检出 | TargetTracker 始终没给出有效像素坐标 |
| B 冲刺前丢失 | 检出过，但在面积达标前丢失 → 搜索 → 超时 |
| C 偏心不冲刺 | 面积达标但一直不居中（对齐门控阻止冲刺）→ 超时 |
| D 冲刺未命中 | 冲刺完成，但客观判据为未击破（距离不够 / 方向偏） |
| E 越界 | 击球阶段触发 `SafetyRecovery` |
| F 其他 | 写明具体现象 |

每一类都要给出**颜色分布和代表性日志片段**。对 D 类必须给出冲刺起点到气球的距离
和冲刺实际位移。分类表就是下一步修什么的依据——**修占比最大的那一类**。

### 步骤 5：针对性修复（按分类结果选，不要全做）

可选方向（都是假设，用分类数据决定做哪个）：
- **D 类为主** → 冲刺距离与面积阈值是否匹配；按实测"面积 8% 时的距离"调整
  `sprint_time/sprint_velocity` 或 `approach_area_threshold`。参数要改在**真正生效的地方**（见步骤 1）。
- **B/C 类为主** → 目标像素平滑（例如对 `center_x` 做短窗滤波）、居中容差、
  紫球打击点位与朝向（`5.3;-1.0;1.0, yaw=-1.5708`）是否让气球一开始就在视野中心附近。
- **E 类** → 降低紫球阶段前进速度或缩小搜索动作幅度；**不改 `safety/*` 默认值**。
- **任何情况下都考虑**：把"超时 → ForceSuccess"改造为"未确认击破 → 回到击球点重试一次 →
  无论结果都返航降落"。收益：一次重试换 25 分；代价：时间分（≤10 分）。
  必须保证返航和降落一定执行；有效重试次数与时间预算写清楚（单局总超时 300 s）。
  如果树来自大模型生成，修改要落在生成链路（提示词模板 / 后处理），并保证
  `mission_once.py` 的正常输出仍能通过。

每项修改：备份 + md5 + 补丁脚本放进 `v3_stability/hit_balloon_v2/patches/`
（沿用 PR #2 的风格：源码形状不符或已打过补丁时拒绝修改，并生成 `restore.sh`）。
**一次只改一个变量**，否则对照实验没有意义。

### 步骤 6：正式回归

- 走 `/home/ubuntu/tcei_baseline_tools/run_formal_trial.sh <color>`（拿共享锁、写 `baseline_runs.csv`），
  **红/紫/蓝各 ≥ 3 局**，并对每局运行 `judge_hit.py`。
- 大模型非法输出（20 s 内结束、无 `mission_result`）单独计数并重跑，不计入失败。
- 顺带记录每局 ArUco 窗口内的 `callbacks/s`（v3 节点每秒输出一次）：
  有没有出现过 0？这是 ArUco 停摆问题至今缺的那份证据，样本可以和本步骤复用。

**收敛规则**：同一结论连续 3 局得到支持即可停止探索、写报告；不要无限开新假设。

---

## 五、交付物（缺一不可）

1. `v3_stability/hit_balloon_v2/deployed_manifest_<日期>.md`（步骤 1）
2. `v3_stability/hit_balloon_v2/tools/judge_hit.py` 及其在已知局上的校准结果（步骤 2）
3. `v3_stability/hit_balloon_v2/patches/` 与 `deployed_diffs/`
4. 报告 `v3_stability/reports/hit_balloon_fix_<日期>.md`，必须包含：
   - 偏航符号测量的原始数据与结论（步骤 3）
   - 失败分类表（每局一行：目录、颜色、类别、关键证据）
   - 每项修复前后**按颜色**的击破率（客观判据）："紫球 修复前 0/4 → 修复后 2/3"，不要形容词
   - 反例：哪些局仍失败、属于哪类
   - ArUco `callbacks/s` 观察结果（包括"0 次复现"这一结果本身）
   - 每项改动的回滚命令
   - 结论适用范围（哪种颜色、哪组参数、哪个部署版本）
5. 发 PR 到 `main`，描述里列出改动了哪些自己负责目录以外的文件（应当没有）

**禁止的表述**："应该可以"、"看起来正常"、"理论上没问题"。

---

## 六、陷阱速查（详见 `AGENTS.md` §6）

- `llm_mission.launch` 是 UTF-8 + CRLF，**不可用 shell `cat >` 往返**，只能字节级定点修改；
  其中 `optimization/*` 四行属于队友 B，不要冲掉。
- `pkill -f <脚本名>` 会杀死自己；用 `pgrep -f "[a]ruco_detect_node"` 再按 PID kill。
- 锁残留 `/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`：确认其中 PID 已死再清。
- 启动仿真必须 `export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority`，否则 xterm 全部秒退。
- C++ 改动必须 `catkin_make --pkg mission_pkg`；Python 改动不需要。
- `v2_time_optimization/`、`v2_1_ego_velocity/` 属于队友 B，不要动。

现在开始：确认服务器无人使用 → 执行步骤 1（只读盘点）→ 步骤 2 → 步骤 3。

===== 复制到这里结束 =====
```

---

## 附：本提示词的设计意图（给你，不用发给 Astra）

- **先盘点、后修改**：PR #2 已经在服务器上叠了 6 个补丁，而且仓库和服务器版本不一致；
  不先拉清单，Astra 的任何对照实验都没有可靠的基线。
- **先定判据、后谈成功率**：observer 的 `hit_balloon_status` 和行为树的 `SUCCESS`
  都只是"冲刺完成"的代理指标，PR #2 唯一的击破证据还是操作员目视。没有客观判据，
  后面所有"击破率"都无法比较。
- **偏航符号用直接测量判定**：悬停 + 固定偏航指令 + 观察像素移动方向，1–2 局即可给出确定答案，
  比用胜负统计便宜得多。这也是"当前版本是否把红球打坏了"这个风险的最快排除方式。
- **按分类修**：明确要求修占比最大的失败类别，并且一次只改一个变量，避免重演 PR #2
  "一晚上连叠 3 个补丁、每个只跑 1 局"的模式。
- **ForceSuccess 改为重试**列为"任何情况下都考虑"，因为它直接影响 25 分阶段的期望得分，
  但同时硬性要求返航降落必须执行，保住 5 分。
- 口令没有写进本文件；需要时手工粘贴，或像 ArUco 交接那样另存一份 FULL 版到 `.scratch/`。
