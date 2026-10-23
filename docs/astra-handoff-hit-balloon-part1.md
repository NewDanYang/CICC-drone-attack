# Astra 交接提示词：先收尾 2.2，再做气球阶段达标（计划第一部分 1.1–1.4）

> **使用方式**：把下面 `=====` 之间的全部内容整段复制发给 Astra。
> 起点是分支 `codex/rule-compliance-verification`（已推送 origin，含 commit `de220af`）。
> **第一件事收尾 2.2，不管结果如何都接着做 1.1–1.4**——这是两件独立的事，用同一个服务器窗口
> 顺序做，不要因为第一件事的结果犹豫要不要做第二件事。
> 外层用 4 个波浪号包裹，是为了让内层 ```bash 代码块在预览里正常显示。

---

~~~~
===== 从这里开始复制 =====

# 任务：收尾大模型校验修复验证，然后让气球阶段（25 分）稳定过关

你在一个真实比赛项目上接手两件事。**先读完本提示词全文，再动手**——这次信息量比较大，
但都是从服务器证据和源码里核对出来的，不是猜测。

先读仓库根目录 `AGENTS.md`（环境、已排除结论、已知陷阱、报告规范）。

---

## 〇、两件事的关系和顺序

**第一件事（约 20–30 分钟）**：你上一轮（2026-10-15）真实模型抽样时发现了一个校验兜底排序的
bug（`distractor_color` 三次重试打平时，兜底选中了完全没打气球的答案）。这个 bug 已经修好
（commit `de220af`），**只经过离线回归测试，没有上机验证**。你需要用真实模型把这一条重新跑一遍，
确认线上行为和离线预期一致。

**第二件事（主要工作量）**：气球阶段（25 分）至今没有在"三球全在场"的真实比赛条件下验证过
稳定成功，而且存在两个已知问题（边界恢复频繁触发、红区使用预设朝向）。这部分和第一件事
**完全独立**——不管第一件事测出什么结果（过了、没过、发现新 bug），都继续做第二件事。
两件事都要做完，报告也分开写。

---

## 一、授权与纪律（和之前几轮一致）

直接做、事后报告：SSH 读写服务器文件、改 `catkin_ws/src/` 下源码（**先备份**）、
`catkin_make --pkg mission_pkg`、重启节点、跑正式试验、清理确认已死的锁、
在服务器上新建/改 `v3_stability/hit_balloon_v2/tools/` 下的工具脚本。

需要先问的只有：改比赛规则禁止项、改安全边界默认值（`safety/*`）、推送到 `main`、
删除别人的实验数据。

纪律：单局不是证据，每个结论至少 3–5 局；给出数字、样本数、反例；禁止"应该可以""看起来正常"；
**第二件事里的 1.3 和 1.4 必须分开改、分开测，不要在同一次编译里同时改两处**——这是"只改一个变量"
的实验纪律，否则边界恢复次数下降说不清是哪个改动的功劳。

---

## 二、前置检查

```bash
export TCEI_HOST=120.209.70.195 TCEI_PORT=30316 TCEI_USER=root
export TCEI_PASSWORD='<向项目负责人索取，不要写进任何会提交的文件>'
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh "echo OK"
```
端口连接被拒绝 = 云主机关机，找有 gpufree.cn 控制台权限的人。

**服务器是全组共用的单实例，动手前必须检查有没有人在用**：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'ls -d /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock 2>/dev/null; tail -1 /home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv; date -u'
```

**同步代码**：
```bash
git fetch origin && git checkout codex/rule-compliance-verification && git pull
```

---

## 三、第一件事：验证兜底排序修复（`balloon_command_missing`）

读 `v3_stability/rule_compliance/README.md` 里"v3 新增"那一节，理解 bug 是什么——
`distractor_color`（"不要碰蓝色气球，扎破红色的气球。"）三次重试都只有一个"疑似多余步骤"
的问题，打平后旧排序保留了**最先出现**的那次，哪怕那次完全没有 `hit_balloon` 行。
新逻辑把"有没有打气球命令"排进排序第一位。

**确认服务器当前状态**：你上一轮（第三轮）处理决定是"保留候选部署"，没有回滚，服务器应该
处于 `mission_once.py` MD5 `1597c5c139632fff4823e8b4d7cadd28` 的状态：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'md5sum /home/ubuntu/model/mission_once.py'
```
不符就停下来问，不要猜。

**部署这一个文件**（其余三个这次没有变化，不需要重新上传）：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
  v3_stability/rule_compliance/deploy/mission_once.py /tmp/rule_compliance/mission_once.py
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
  v3_stability/rule_compliance/deploy/deploy_rule_compliance.sh /tmp/rule_compliance/deploy_rule_compliance.sh
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh 'bash /tmp/rule_compliance/deploy_rule_compliance.sh'
```
部署脚本这次会核对线上旧 MD5 是 `1597c5c1...`、新 MD5 是 `fca24bf1...`，和其余三个文件
（旧=新，确认没被别人动过即可，不会实际改动）。重启仿真环境（含大模型进程）。

**验证**：用 `v3_stability/rule_compliance/tools/llm_paraphrase_probe.py`
（你上一轮已经给它加了 `--case-ids` 过滤参数）：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; source /opt/ros/noetic/setup.bash; \
   /opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/llm_paraphrase_probe.py \
   --case-ids distractor_color --output /tmp/rule_compliance/distractor_recheck --samples 8'
```
8 次而不是 5 次，因为上一轮的真实失败样本只出现了 1/5 次，想更有把握地看到它复现或消失。

**判据**：
- **主要判据**：抽查每一次的 `samples.jsonl`，只要某次触发了多轮重试且最终 `final_commands`
  里缺少 `hit_balloon:` 行，就是修复没生效，停下来报告，不要继续改。
- 探针自己的"严格通过率"（要求带 `command` 标签）不是这次要看的指标——上一轮已经确认探针这
  个判据比线上真实逻辑更严，不代表部署行为有问题。这次只看"兜底选中的答案里有没有打气球命令"。
- 把结果写进 `v3_stability/reports/rule_compliance_20261015_v3b/REPORT.md`（新目录，不要覆盖
  `_v3` 那份），不管是否复现都要写清楚；复跑一遍离线测试（期望 28/28）附上。

做完这一步，**不管结果如何**，往下做第二件事。

---

## 四、第二件事：气球阶段（25 分）稳定性

### 背景（已核实，不要重新发现）

- `v3_stability/hit_balloon_v2/tools/run_with_scene_snapshots.sh` 已经实现了"跑正式试验 +
  场景前后快照"的包装，**默认要求开局 3 个气球 Actor**（`TCEI_REQUIRE_FRESH_SCENE=1`），
  不是 3 个就直接退出（exit 5），**不会自动重置场景**——这是本次要补的洞。
- `v3_stability/hit_balloon_v2/tools/judge_hit.py` 做击破判定，依赖
  `actor_scene_calibrations.json`（按 `sim_pid` + 完整三 Actor 名单做的颜色映射，
  每次仿真环境重启 `sim_pid` 都会变，旧的映射不能跨实例复用）。
  `v3_stability/hit_balloon_v2/tools/reset_scene_checked.sh` 会终止并重启整个仿真环境
  （约 2–4 分钟），这意味着**每次重置都会让颜色校准失效**。
- `visual_servo.cpp`（三阶段状态机：ALIGN → APPROACHING → SPRINTING）里，`SPRINTING` 阶段
  固定跑 `sprint_time_`（默认 1.2 s）× `sprint_velocity_`（默认 1.5 m/s）才结束，**不检查
  冲刺过程中是否已经撞到气球**，即使目标面积已经暴增或目标丢失也会跑完全程——这正是撞球后
  继续冲向边界、触发安全恢复的原因。
- `bt_ros.cpp` 的 `hit_balloon:颜色` 命令生成逻辑里，先用 `balloon_zone_<区>/yaw`
  （红区=A区=`3.14159`）给一个**固定朝向**的 `GoTo`，再启动 `VisualServo`。
  `VisualServo` 自己其实已经有一套"目标丢失 → 原地悬停扫描 yaw 寻回"的逻辑
  （`isTargetLost()` 分支，`search_anchor_`），所以红区固定朝向理论上不是必需的——
  这正是 1.4 要验证的假设。当前 `llm_mission.launch` 里 A 区（红）的
  `approach_pos` z=1.5，B/C 区是 0.7，这就是"红区专用 z=1.5"。

### 1.1：每局重置场景，保证三球全在场，统计误击与"少两只球"

**目标**：红、紫、蓝各 ≥3 局，每局开局都是 3 个 Actor（真实比赛条件）；
统计两个数字，目标都是 0：
- **误击次数**：局结束时消失的 Actor，有独立证据表明**不是**目标颜色（见下面怎么拿证据）。
- **同局少两只球的次数**：局结束时 Actor 数 ≤1（本该只打一个，却多删了一个）。

**做法**：
1. 包一层循环脚本（放 `v3_stability/hit_balloon_v2/tools/` 下，文件名自定，比如
   `run_fresh_scene_loop.sh`）：调用 `scene_snapshot.py before` 探活动 Actor 数，
   不是 3 就调用 `reset_scene_checked.sh` 重启环境（等 `environment_started=1`）后重试；
   是 3 才调用 `run_with_scene_snapshots.sh <color>`。
2. **每局都开 `TCEI_CAPTURE_REAL_FRAMES=1`**（`run_with_scene_snapshots.sh` 已经支持这个
   环境变量），拿到真实相机帧。不要依赖 `actor_scene_calibrations.json` 里现成的颜色映射——
   按场景设计，每局重置后 `sim_pid` 都会变，旧映射大概率对不上这次的 Actor 名单，
   也没有时间给 9 局分别做"同实例多色消去法"校准。
3. **判定"是不是误击"的证据来源改成实时相机帧，不是事后 Actor-ID 反查**：
   每局结束前（Actor 刚消失那一刻附近）截取的真实帧，看画面里还能不能看到目标色气球、
   以及冲刺末段画面主体是不是目标色——这是 `capture_real_frames.py` 已经在做的事，
   不需要新工具，只是要求**每局都开**而不是挑着开。如果某局拿不到足够置信的帧证据，
   如实写"无法独立确认颜色"，不要默认算成功。
4. 9 局的 Actor 计数本身（3→2 还是 3→1 还是 3→3 不变）不依赖任何颜色判定，**一定要记**，
   这是最基本、最可信的数字。

**验收**：9 局（或更多，直到红紫蓝各 ≥3 局有效数据）表格：局号、颜色、开局 Actor 数、
结局 Actor 数、是否有相机证据确认目标色、独立误击判定。误击和"少两只球"都是 0 才算过。

### 1.2：给击破时刻定时间

**先验证一件事，再决定怎么做**：UE 控制台有没有 `obj gc`（强制垃圾回收）命令，
调用后 `scene_snapshot.py` 式的 `obj list class=BP_Balloon_C` 查询是不是能立刻反映
最新的 Actor 数，而不是像现在这样要等到 `settled`（默认 125 s 后）才可信。
照着 `scene_snapshot.py` 里 `UE4CtrlAPI().sendUE4Cmd(...)` 的调用方式，换成
`sendUE4Cmd("obj gc")`（具体命令字符串自己在 UE 控制台文档或试验里确认，这只是起点），
找一局故意在冲刺中途发一次 `obj gc`，看 Actor 数是不是比不发的时候更快掉到 2。

- **如果 `obj gc` 能让 Actor 数即时更新**：写一个新的采样循环，任务执行期间每 1–2 s
  调一次 `obj gc` + `obj list`，拿到比现有 `before/after/late/settled` 更细的时间序列，
  找到 Actor 数真正发生变化的那个采样点，±1 个采样间隔就是击破时刻的误差范围。
- **如果不能**（GC 真的有延迟，调用也不能强制）：改用间接证据——`judge_hit.py` 已经解析
  遥测里的 `SPRINT_START`/`Sprint completed` 时间戳和 `[TargetTracker]: Tracking at pixel`
  计数；把这些和里程计（`/rflysim/uav1/local/odom`，遥测里应该有定期采样）对齐，
  估计无人机离气球最近的那个时刻，作为击破时刻的**估计值**，而不是精确值，报告里要写清楚
  这是估计不是实测。
- 同时和边界事件对齐：边界触发的日志是 `ROS_ERROR("[Safety] DRONE OUT OF BOUNDARY! ...")`
  （在遥测 `rosout` 事件里能 grep 到），时间戳和上面估出来的击破时刻比一比，确认"是不是
  撞完气球才触发边界"这个因果顺序，而不是两者无关的巧合。

**验收**：对 1.1 里拿到的每一局有效数据，给出击破时刻估计（±2 s 或更细），并说明是
"接近途中撞破"（APPROACHING 阶段面积已经很大但还没进 SPRINTING）还是"冲刺撞破"
（SPRINTING 阶段中途）。

### 1.3：撞到气球后立即刹车悬停——只改这一个变量

**只改 `visual_servo.cpp` 的 `SPRINTING` 分支，不要同时碰 1.4 的内容。**

当前代码（`v3_stability/hit_balloon_v2/deployed_source/visual_servo.cpp` 第 239–267 行附近，
但服务器上的实际内容和版本号要你自己核对 MD5，不要假设和这份快照完全一致）：

```cpp
case SPRINTING: {
    double sprint_dt = (ros::Time::now() - sprint_start_time_).toSec();
    if (sprint_dt >= sprint_time_) {
        // ... sendHoverCommand(); return NodeStatus::SUCCESS;
    }
    if (!isTargetLost()) {
        publishVelocityWithYawRate(sprint_velocity_, 0, vz, yaw_rate);
    } else {
        publishVelocityWithYawRate(sprint_velocity_, 0, 0, 0);
    }
    break;
}
```

`current_ratio`（目标面积占画面比例）和 `isTargetLost()` 在 `onRunning()` 顶部每 tick
都已经算好，`max_area_ratio_` 也已经在跟踪冲刺前的最大面积。加一个提前结束的判据：

- **目标面积突增**：`current_ratio` 比 `max_area_ratio_`（冲刺前的历史最大值）大出一截
  （具体倍数/阈值自己定，比如突增到冲刺前最大值的 1.5× 以上，或绝对值超过一个很高的阈值，
  比如 0.5），说明已经撞得非常近；
- **近距离丢失**：`isTargetLost()` 变 true，且丢失前最后一帧的 `current_ratio` 已经很高
  （比如超过 `approach_area_threshold_` 的好几倍），说明目标大概率是被机体遮挡/碰撞而不是
  正常意义上的"看不见了"。

满足任一条件：调用 `sendHoverCommand()`，`return NodeStatus::SUCCESS`，提前结束冲刺，
不等 `sprint_dt >= sprint_time_`。打印一行日志说明是哪个判据触发、当时的
`current_ratio`/`max_area_ratio_`/`sprint_dt`，方便事后核对。

**按项目既有惯例写 MD5 校验的补丁脚本**（参考
`v3_stability/hit_balloon_v2/patches/patch_sprint_center_gate.py` 等已有写法：
`root/relative` 路径是 `src/mission_pkg/src/nodes/action/visual_servo.cpp`，先核对
服务器当前这份文件的 MD5，不符就不改），**先在服务器上确认当前 `visual_servo.cpp` 的
实际 MD5**，不要假设等于本仓库快照里记的任何历史值——你上几轮工作可能已经让它变了。
改完 `catkin_make --pkg mission_pkg`，重启节点。

**验收**：红、紫、蓝各 ≥3 局（可以复用 1.1 的循环工具），和 1.1/1.2 测到的"改前"基线比：
- `boundary_violation_count` 从 7/9（2026-10-13 基线）降到 ≤1/9；
- 击破率（Actor 数正确减少、且独立确认颜色）不低于改前。

两条都要有数字支撑，不能只凭感觉说"看起来好多了"。

### 1.4：红区入场朝向改为感知驱动——只改这一个变量，等 1.3 验收完再做

**前提：1.3 已经验收完、单独出过报告，才开始改这里。**

目标：去掉 `balloon_color_red` 对应区（当前是 A 区）的固定入场朝向
`balloon_zone_A/yaw`，改成"到达 `approach_pos` 后原地悬停、靠 VisualServo 自己的
目标丢失扫描逻辑找到红色气球、自然对准"，同时去掉红区专用的 z=1.5
（`balloon_zone_A/approach_pos` 当前 z=1.5，B/C 区是 0.7，改成和 B/C 一致或你认为更合理的值，
但不要再保留"红区单独更高"这个特例，除非你有证据证明去掉之后会撞到什么）。

**具体改法建议（起点，不是唯一做法，自己判断）**：
- `bt_ros.cpp` 里 `hit_balloon:颜色` 的命令生成逻辑，针对 `zone == "A"`（或者改成更通用的
  "不依赖颜色硬编码"的方式）跳过固定朝向的 `GoTo ... yaw=...`，改成不带 `yaw` 参数的
  `GoTo`（保持当前朝向到达 `approach_pos`），让后续的 `VisualServo` 启动时如果看不到目标，
  自动进入它已有的"目标丢失→原地扫描"逻辑去找红色气球。
- 同步改 `llm_mission.launch` 里 `balloon_zone_A/approach_pos` 的 z，去掉红区特例。
- **不要**顺手把 B/C 区也改了——这次只动红区，否则"是不是去掉预设点位帮到了红球"这个
  结论会被别的改动污染。

**验收**：红球 ≥3 局（可以是 1.3 验收之后接着跑的新一批），红球击破率不低于改之前
（即不低于 1.3 验收批次里红球的表现）；检查源码确认 `balloon_zone_A` 不再有硬编码的 `yaw`
值传给 `GoTo`（或者如果你认为完全去掉 yaw 不安全，改成别的方案，但要在报告里写清楚
为什么，以及这还算不算"预设位置点"——这关系到规则里"禁止预设位置点，审查后每阶段 −5"
那一条）。

---

## 五、交付物

每个子任务（第一件事 + 1.1 + 1.2 + 1.3 + 1.4）**分别**产出证据和报告，不要混在一起：

- `v3_stability/reports/rule_compliance_20261015_v3b/`——第一件事。
- `v3_stability/reports/hit_balloon_part1_1.1/`、`.../1.2/`、`.../1.3/`、`.../1.4/`——
  第二件事的四个子任务，各自的试验目录、CSV、判据脚本输出、`REPORT.md`。
  1.2 可以和 1.1 共用试验数据（同一批 9 局，只是从里面抽不同的指标分析），
  1.3 和 1.4 **必须是各自独立的试验批次**。
- 每个 `REPORT.md` 都要有：原始证据路径、样本数、改动前后对比数字、回滚命令、
  结论适用范围（样本量多小、哪些情况没测到）。
- C++/launch 改动按项目惯例写 MD5 校验的补丁脚本，放进
  `v3_stability/hit_balloon_v2/patches/`，命名延续现有风格（比如
  `patch_sprint_abort_on_contact.py`、`patch_red_entry_perception.py`）。

发 PR 到 `main`，不要直接推 `main`。分支可以继续用 `codex/rule-compliance-verification`，
或者考虑新建一个专门分支（这个分支名字已经不太描述这次的工作内容了，你自己判断要不要换，
换的话把之前的记录在新分支 PR 描述里链接过去，不要丢上下文）。

---

## 六、陷阱速查（详见 `AGENTS.md` §6，补充这次特别相关的）

1. **每次重置场景后 `sim_pid` 会变**，`actor_scene_calibrations.json` 里现成的映射对不上
   新实例，不要往这个文件里加基于单次观察就下结论的新条目——这个文件目前的条目都是靠
   同一实例内 3 色消去法+相机颜色分类交叉验证出来的，单局单色不足以支撑同等置信度的条目。
2. **C++ 改动必须 `catkin_make --pkg mission_pkg` 才生效**，Python 改动不用。
3. `reset_scene_checked.sh` 会杀掉仿真进程组，**执行它的 SSH 命令本身不能和被杀的进程共享
   进程组**（脚本注释里写了这一点），照着现有脚本的调用方式来，不要自己改调用方法。
4. 锁残留、`pkill -f` 自杀问题，和之前几轮一样，见 `AGENTS.md` §6。
5. 1.3 和 1.4 的验收批次**不能共用同一批试验数据**，否则无法归因是哪个改动起作用。
6. 改 `visual_servo.cpp` 或 `bt_ros.cpp`/launch 前，**先在服务器上用 `md5sum` 核对实际版本**，
   不要假设和本仓库快照里任何历史记录的 MD5 一致——这几个文件这几轮被改过很多次。

===== 复制到这里结束 =====
~~~~

---

## 附：本提示词的设计意图（给你，不用发给 Astra）

- **把"收尾 2.2"和"做 1.1–1.4"明确切成两件独立的事，并且显式要求不管第一件事结果如何都做
  第二件事**：这是直接响应你的指示，避免 Astra 因为对兜底排序修复的验证结果产生犹豫（比如
  "这个还没验证完，我是不是该先缓一缓"）而拖慢第二部分的进度。
- **1.1 没有照搬原计划里"保证三球都在场"的字面实现方式，而是指出现有工具已经做了一半**
  （`run_with_scene_snapshots.sh` 已经要求 3 Actor，只是不会自动重置）——这是从代码里核实出来的，
  避免 Astra 重新发明一套场景管理逻辑。
- **1.1 的颜色判定特意绕开了 `actor_scene_calibrations.json` 的现成校准体系**，因为"每局重置"
  和"同实例多局消去法校准"这两个要求在结构上是冲突的（每次重置都换一个新的 UE 实例，旧校准
  用不上，而要建立新校准又需要同实例多局——但 1.1 恰恰要求每局都是全新实例）。改用每局都开的
  真实相机帧作为独立证据源，绕开这个结构性冲突，而不是让 Astra 自己撞上这个矛盾才发现。
- **1.2 要求先做"`obj gc` 能不能用"的可行性验证，再决定走精确路线还是估计路线**：这是因为
  `judge_hit.py` 的文档里已经写明 UE 垃圾回收有延迟这个已知限制，不先验证清楚就直接堆高采样
  频率，很可能只是把同样滞后的数据采得更密，不会真正提高时间精度。
- **1.3 和 1.4 强制要求分开改、分开验收，且 1.4 必须等 1.3 验收完才开始**：这是"只改一个变量"
  原则的具体落地，原计划文本里这句话容易被理解成"这次实验只变一个参数"，这里把它具体化成
  "两个代码改动必须用各自独立的试验批次验收，不能在同一批数据上同时评估两个改动的效果"。
