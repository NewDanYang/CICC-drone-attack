# 队友 A 工作指示：修复 hit_balloon 阶段失败 + 验证 ArUco 停摆是否解决

> 发给队友 A 的完整工作说明。整段复制发送。

---

```
===== 从这里开始复制 =====

# 任务：诊断并修复 hit_balloon（击球）阶段失败；验证 ArUco 回调停摆问题是否已解决

## 开工前必读（按顺序）

1. 仓库根目录 `README.md` —— 文件索引
2. 仓库根目录 `AGENTS.md` —— **必读**。里面有环境启动方式、已排除的错误结论、
   已知陷阱、报告规范、多人协作约定。本文件里不重复的细节都在那里。
3. `v3_stability/reports/aruco_fix_20261006.md` —— 上一轮 ArUco 工作的原始记录，
   里面的试验数据是你这轮诊断的起点。

**不要在没读完 AGENTS.md 的情况下开始**——里面记录的坑都是真实踩过的，
重新踩一遍只会浪费你的时间。

---

## 访问方式

```bash
export TCEI_HOST=120.209.70.195
export TCEI_PORT=30316
export TCEI_USER=root
export TCEI_PASSWORD='<找项目负责人要，不要把它提交进仓库>'
```

Windows / Git Bash 调用 `v3_stability/tools/srvctl.py` 时都要加 `MSYS_NO_PATHCONV=1`
前缀，否则远程路径会被转换成 Windows 路径而失败（`AGENTS.md` §2.1 有说明）。

## 你有完全授权

按 `AGENTS.md` §3.2：编辑源码、重启节点、跑正式试验、编译、清理僵尸进程/锁，
这些事直接做、事后报告，不要停下来问。只有改比赛规则禁止项、删别人数据、
推送到 `main`（而不是发 PR）这几件事需要先问。

---

## 一、问题是什么（已有数据，不要重新发现）

上一轮工作把 ArUco（二维码）识别从间歇性失败修到了**红 9/9、紫 2/2、蓝 2/2 全部成功**
（用的是 `v3_stability/aruco/aruco_detect_node.py`，CLAHE + 3x 上采样 + subpix，
交互显示窗口默认关闭）。

但二维码修好之后，同一批 14 局有效试验里，**只有 4 局完整通过全程**：

```
完整成功：20261006T150933(红)、20261006T162450(红)、
         20261006T181920(紫)、20261006T182538(蓝)
其余 10 局：全部卡在 hit_balloon 阶段
         （bt_success=true 但 mission_success=false）
```

汇总数据见 `baseline_tools/results/baseline_runs.csv`（2026-10-06 那批行），
原始试验目录在服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/`。

**这是当前全场最大的失分点**：hit_balloon 单阶段 25 分，是全题目最高分值的阶段，
目前成功率约 29%。这是你的首要任务。

### 已知背景（不是结论，是你要去验证的假设之一）

之前有一个**已经修复并验证过**的故障：安全边界恢复死锁（`v1_safety_recovery/`，
恢复目标点卡在边界上导致永远无法确认完成）。该修复已部署，并且做过**主动构造越界**
的验证——单局连续 3 次越界，全部在 2-5 秒内恢复完成（证据见
`v3_stability/reports/boundary_proof_raw.txt`）。

**这 10 局新的 hit_balloon 失败，和那个已修复的死锁是不是同一回事，完全没人查过。**
两种可能，对应完全不同的修法：

1. 确实触发了边界恢复，但这次没能完成（说明之前的修复有遗漏或被别的改动覆盖了）
2. 根本没有触发边界，失败发生在别处（比如 VisualServo 一直找不到气球、
   TargetTracker 超时、行为树某个节点报 FAILURE）

**不要假设是哪一种。去读日志，让数据告诉你。**

---

## 二、诊断步骤

### 步骤 0：确认服务器状态

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh "echo OK"
```

连不上（`Connection refused`）说明云主机关机了，这个你解决不了，去找有
gpufree.cn 控制台权限的人开机。连上之后按 `AGENTS.md` §2.3 启动仿真环境。

### 步骤 1：先看已有数据，不急着重新跑

`/home/ubuntu/tcei_baseline_tools/results/formal_trials/` 下那 10 局失败的目录
可能还在（看服务器有没有被清理过）。对每一局，提取并记录：

```bash
# 以目录名替换 <dir>
cat /home/ubuntu/tcei_baseline_tools/results/formal_trials/<dir>/observer.out
```

重点字段：`failure_stage`、`failure_reason`、`safety_boundary_triggered`、
`boundary_recovered`、`boundary_violation_count`。

然后从对应的 `*_telemetry.jsonl` 里过滤这些关键词，按时间顺序摘出来：

```
SafetyRecovery   (ENTER / COMPLETE / confirmation reset / RELEASE)
VisualServo      (Visual Servo Started / Target lost / SPRINT)
TargetTracker    (Detecting target / timeout)
ARUCO / aruco    (确认不是二维码阶段误报——这轮应该都已通过)
```

可以照抄 `v3_stability/tools/check_recovery.py` 的思路写一个类似的提取脚本，
或者直接复用它（它已经能识别 SafetyRecovery 的进入/完成/重置）。

### 步骤 2：分类

把这 10 局按失败特征分组（大概率不止一种）。每组至少要能回答：

- 有没有触发 `SafetyRecovery`？触发了几次？每次有没有 `COMPLETE`？
- 如果没触发边界，行为树在哪个节点、因为什么条件报的 FAILURE/超时？
- 气球识别（TargetTracker/VisualServo）本身有没有找到目标？找到后冲刺
  （SPRINT）有没有成功？

### 步骤 3：定位代码根因

根据分组结果，去读相关源码（不要猜）：

- 安全恢复：`/home/ubuntu/catkin_ws/src/mission_pkg/src/mavros_cnt.cpp`
- 视觉伺服：`/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp`
- 目标跟踪：`/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/perception/target_tracker.cpp`

如果发现是安全恢复相关改动被后续某次部署覆盖/回退了，先确认当前服务器
实际运行的 `mavros_cnt.cpp` 的 md5 和仓库 `v1_safety_recovery/src/mission_pkg/src/mavros_cnt.cpp`
是否一致——上一轮就踩过"仓库有修复但服务器没部署"这个坑。

### 步骤 4：修复与回归验证

- 改之前备份原文件，记 md5（`AGENTS.md` §3.3）
- **C++ 改动必须 `catkin_make --pkg mission_pkg`**，Python 改动不需要
- 修复后**至少跑 5 局**做回归（不能 1 局就下结论），覆盖红/紫/蓝至少各 1 局
- 如果样本不足或结果不稳定，如实写"样本不足，暂不能下结论"，不要凑结论

---

## 三、第二任务：ArUco 回调停摆是否真的解决了（优先级低于 hit_balloon）

### 背景

之前发现过一次真实故障：ArUco 节点 20 秒识别窗口内，图像仍以 10Hz 正常到达
（独立采集节点同时段收到 877 帧），但检测节点的图像回调只执行了 1 次
（正常应有约 10 次节流日志）。怀疑是 `cv2.imshow`/`waitKey` 阻塞了订阅回调所在线程。

上一轮部署了 `debug_display` 默认关闭 + 独立 Timer 驱动的 `callbacks/s` 诊断
（能在回调真停摆时直接打印 `callbacks/s=0`，不用再靠"没有日志"这种间接推断），
但跑的 13 局里**一次都没有复现过这个停摆**，所以"是否解决"目前没有证据，
不是"已解决"也不是"未解决"，是"未知"。

### 你要做的

1. 多跑几轮（建议 10 局以上，可以和 hit_balloon 诊断的试验数据复用，
   不用专门为这个另跑）
2. 如果复现了停摆：看 `callbacks/s` 日志是不是真的降到 0，这就实锤了根因
3. 如果想做真正的对照实验：把 `debug_display` 切回 `true`，对比停摆复现率
   （之前的"修复"假设就是关掉显示能避免回调被阻塞，这个假设从没被验证过）
4. 如实报告复现次数（包括"0 次复现"这个结果本身也是信息，要写清楚）

---

## 四、Git 工作流

```bash
git checkout -b fix/hit-balloon-diagnosis
```

你的地盘（改这些目录不用问队友 B）：

```
v1_safety_recovery/
v3_stability/aruco/
v3_stability/reports/   （新增你自己的报告文件，不要改队友B可能在写的报告）
```

**不要动** `v2_time_optimization/`、`v2_1_ego_velocity/`——那是队友 B 的工作区。

改完发 PR 到 `main`，附上报告链接。

## 五、服务器时间共享

跑试验前先确认没人在用（`AGENTS.md` §9 有现成命令）。看到最近几分钟有新试验记录，
先在团队沟通渠道确认一下再抢服务器。

## 六、报告规范（`AGENTS.md` §8，再重复一遍要点）

必须包含：**原始试验目录路径**、**样本数与对照组**、**修复前后对比的数字**、
**反例（哪些情况仍会失败）**、**回滚命令**。

**禁止**："应该修好了"、"看起来没问题"。
**要求**：具体数字和路径，经得起别人去复现检查。

产出位置：`v3_stability/reports/hit_balloon_fix_<日期>.md`

现在开始。先确认服务器状态，然后从已有的 10 局失败数据入手，不要急着重新跑。

===== 复制到这里结束 =====
```
