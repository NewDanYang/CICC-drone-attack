# Astra 交接提示词：规则合规候选 v2——只做验证 B（大模型新措辞抽样）

> **使用方式**：把下面 `=====` 之间的全部内容整段复制发给 Astra。
> 起点是分支 `codex/rule-compliance-verification`（已推送 origin，含 commit `d763d0d`，
> 尚未合入 main）。这是对 2026-10-15 那轮上机验证的后续。**这次只做验证 B，不要重跑窗口计时**——
> 2.1（窗口是否退化）已经结清，原因见下面第〇节。读完再动手，不要重新发现已经发现的事。
> 外层用 4 个波浪号包裹，是为了让内层 ```bash 代码块在预览里正常显示。

---

~~~~
===== 从这里开始复制 =====

# 任务：验证规则合规候选 v2 的大模型新措辞修复是否生效（不需要重测窗口）

你在一个真实比赛项目上接手第三轮上机验证。前两轮你都做完了，产出的证据扎实、结论诚实。
这次范围比前两轮窄：**只验证大模型的新措辞修复，窗口计时不需要再测**。
先读完本提示词，再读 `v3_stability/reports/rule_compliance_20261015/REPORT.md`
（含事后追加的"补充"一节）和 `v3_stability/rule_compliance/README.md`，再动手。

先读仓库根目录 `AGENTS.md`（环境、已排除结论、已知陷阱、报告规范）。

---

## 〇、2.1（窗口是否退化）已经结清，不要重做

你在 2026-10-15 那轮做的九局无抓屏计时发现：3/9 局 ArUco 窗口耗时 0.309–0.349 s，
超过旧版九局最大值 0.217 s，于是按"窗口无退化"门槛判定未通过，回滚了候选。
这个回滚决定在当时的数据下是合理的。

事后（同一天，`REPORT.md` 补充一节）做了一次复核：把 `window_s` 按 `callbacks`
（定位二维码用了几次图像回调）分层后看，那三个超时局全部是 `callbacks=3`，
换算成**每次回调的耗时**是 0.103–0.116 s，和旧版 `callbacks=1` 样本的
0.036–0.155 s 区间完全重叠——**不异常**。窗口的主线程绘制改动只影响每次回调里
多做的事（把标注好的帧交给显示循环），不参与 ArUco 角点检测本身，没有机制能让
"需要几次回调才能锁定"这件事变化。旧版 19 条样本从未出现过 `callbacks=3`，
更可能是旧版样本量不够大、没抽到这种情况（`callbacks=2` 在旧版里也只出现过 2/19 次）。

**结论：没有证据支持窗口代码本身存在处理时延，可以认为无明显退化。**
详见 `v3_stability/reports/rule_compliance_20261015/timing/callback_count_stratified_analysis.md`。

**所以这一轮：**
- **不需要**再跑一次多局无抓屏计时去"确认"窗口没问题——已经确认了。
- **不需要**改动 `aruco_detect_node.py` 或 `det_color.py`，它们这次没有任何代码变化
  （和 2026-10-13 版本 MD5 完全相同：`43c3bc40.../348dd7d0...`）。
- **直接部署、直接进入大模型新措辞抽样**。如果抽样过程中你观察到某些局 ArUco 耗时
  仍然偏长，**先查一下是不是又是 `callbacks=3` 这种情况**（看 `window_s/callbacks`），
  而不是立刻假定候选又退化了——除非这次连"每次回调耗时"本身都变长了，那才是真退化。

---

## 一、授权与纪律（和前两轮一致，不重复展开）

直接做、事后报告：SSH 读写服务器文件、部署四个文件、重启仿真环境、跑大模型抽样、
清理确认已死的锁、在服务器上改 `tools/llm_paraphrase_probe.py` 加一个 case 过滤参数。
**只改 `v3_stability/rule_compliance/` 和 `v3_stability/reports/` 下的内容**。

需要先问的只有：改比赛规则禁止项、改安全边界默认值、推送到 `main`、删除别人的实验数据。

纪律：给出数字、样本数、反例；禁止"应该可以""看起来正常"；**不要为了让正确率数字
好看而放宽判据**——这是前两轮一直强调的纪律，这次同样适用。

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
有锁、或 CSV 最近 10 分钟内有新行 → 先去团队渠道确认，不要清锁抢占。

**同步代码**：
```bash
git fetch origin && git checkout codex/rule-compliance-verification && git pull
```

**确认服务器当前状态是已回滚的旧版（你上一轮亲手回滚的那个状态）**：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'md5sum /home/ubuntu/model/mission_once.py /home/ubuntu/model/prompts/mission_prompt.txt \
   /home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py \
   /home/ubuntu/catkin_ws/src/object_det/scripts/det_color.py'
```
期望：`mission_once.py`=`4b0ae381b683b7c38d30baf808ed1346`、
`prompts/mission_prompt.txt`=`321f9b78eb3ad477172f37c70d8b921f`、
`aruco_detect_node.py`=`0f15e84bdaed68c85d3b6b6ee5e33788`、
`det_color.py`=`9eda726899abaf4f951f6b03a08c11ad`。不符就停下来问。

---

## 三、部署（和上一轮完全一样的四个文件，MD5 没有变化）

```bash
for f in mission_once.py mission_prompt.txt aruco_detect_node.py det_color.py deploy_rule_compliance.sh; do
  MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
    v3_stability/rule_compliance/deploy/$f /tmp/rule_compliance/$f
done
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh 'bash /tmp/rule_compliance/deploy_rule_compliance.sh'
```
脚本做的检查和上一轮一样：有正式试验锁时拒绝、核对四个线上文件旧 MD5、备份并生成
`restore.sh`、复制后再校验新 MD5。把完整输出抄进报告，记下备份路径。

重启仿真环境（含大模型进程）：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; cd /home/ubuntu/tcei_baseline_tools; setsid nohup bash ./start_sim_environment.sh > /tmp/sim_start.log 2>&1 < /dev/null &'
# 等 2–4 分钟，直到 /tmp/sim_start.log 出现 environment_started=1
```

**这次不需要跑正式试验去测窗口**，大模型抽样不依赖飞行，可以在仿真环境起来、
`roscore` 可用之后直接做（`mission_once.py` 的 `load_model` 需要 `rospy.init_node`，
但不需要无人机真的起飞）。

---

## 四、验证 B：大模型新措辞抽样（这是本轮唯一的验证内容）

用 `v3_stability/rule_compliance/tools/llm_paraphrase_probe.py`（复用线上同一份
`mission_once.py` 的函数，不 publish，不会驱动无人机）。

### 第一步：给脚本加一个 case 过滤参数（直接改这份共享脚本，不用另外复制）
当前脚本只有 `--list-cases`，没有"只跑指定几个 case"的参数。加一个
`--case-ids`（逗号分隔的 case_id 列表，不传则跑全部 20 套），这是对现有脚本的
向后兼容增强，不影响默认行为。改完先跑 `--list-cases` 确认没有破坏原有逻辑，
再跑一次全量（见第三步）确认行为和之前一致。

### 第二步：针对性复测 4 套上两轮未经真实模型验证过的措辞，每套 ≥5 次采样
这 4 套是新 prompt 范例和 `single_action_problems()` 校验专门针对的目标
（`blue_ball`、`red_yanse`、`distractor_color`、`step_land`，对应 2026-10-14
那轮分别是 9/9、9/9、9/9、3/3 必现失败）：

```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; source /opt/ros/noetic/setup.bash; \
   /opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/llm_paraphrase_probe.py \
   --case-ids blue_ball,red_yanse,distractor_color,step_land \
   --output /tmp/rule_compliance/paraphrase_v3_targeted --samples 5'
```

**判据**：这 4 套之前是 9/9、9/9、9/9、3/3 必现失败。这次**至少要有明显改善**——
不要求 100%（模型有随机性），但如果仍然接近全部失败，说明 prompt 范例或
`single_action_problems()` 没有真正起作用，需要回去看范例是不是写得不够像、
或者正则没覆盖到实际措辞，**不要为了让数字好看而放宽判据**。
把每个失败样本的原始回答留下来，不要只留汇总数字。

### 第三步：全部 20 套复测（≥3 次采样，和上两轮口径一致）
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; source /opt/ros/noetic/setup.bash; \
   /opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/llm_paraphrase_probe.py \
   --output /tmp/rule_compliance/paraphrase_v3_full --samples 3'
```
**判据**：总体严格正确率 ≥95%，样本 ≥40（`area_no_color` 类不计入分母）。
给出错误类型分布，和上一轮（31/54 = 57.4%）逐项对比，写清楚哪几类还在失败、
失败模式和上一轮是否一致、是否出现了上一轮没有的新失败模式。

**耗时预期**：`single_action_problems()` 触发时会多重试一轮，所以这次单次生成
耗时 P50/P95 可能比上一轮（2.894 s / 6.155 s）略高，继续记录但不算失败，
除非明显超出比赛现场能接受的等待时间。

### 第四步（可选，只在前两步都通过之后做）：3 色各 1 局正式试验确认端到端没问题
真实模型配新 prompt 在完整飞行任务里会不会出现异常，用极少的样本量快速确认一下
（不是重新论证窗口退化，只是确认候选在真实飞行里能正常走完全程）：
```bash
for c in red purple blue; do
  MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
    "export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; cd /home/ubuntu/tcei_baseline_tools; \
     setsid nohup bash ./run_formal_trial.sh $c > /tmp/trial_v3_$c.log 2>&1 < /dev/null &"
  # 串行，等上一局结束、锁释放再跑下一局
done
```
**这一步只是端到端冒烟测试，不是窗口计时的第二次验证**——如果某局 ArUco 耗时
又出现偏高，先按第〇节的方法查一下是不是 `callbacks=3`，不要直接下"又退化了"的结论。

---

## 五、交付物

放在 `v3_stability/reports/rule_compliance_20261015_v3/`（和上一轮报告目录区分开，
避免互相覆盖）：

1. `deploy_log.txt`——部署脚本完整输出 + 备份路径。
2. `llm_paraphrase/targeted/` 和 `llm_paraphrase/full/`——第二、三步的 JSONL + CSV +
   正确率 + 错误类型分布，并与 2026-10-14 那轮逐项对比。
3.（如做了第四步）`smoke_trials/`——3 局的目录名、各阶段结果、ArUco 耗时和 `callbacks`。
4. `REPORT.md`——一页：
   - 4 套针对性措辞这次的正确率，和之前 9/9、9/9、9/9、3/3 必现失败对比；
   - 全量 20 套正确率，和上一轮 57.4% 对比，是否过 95%；
   - 最终结论：候选是否可以进入合并评估，还是需要再改一轮 prompt/校验；
   - 回滚命令（无论用没用到都要写）；
   - 结论适用范围。
5. 本地离线测试复跑：
   ```bash
   cd v3_stability/rule_compliance
   PYTHONIOENCODING=utf-8 python tests/test_mission_once_fallback.py   # 期望 25 条 PASS、0 失败
   PYTHONIOENCODING=utf-8 python tests/test_aruco_display_loop.py      # 期望 6/6
   ```

发 PR 到 `main`，不要直接推 `main`。分支继续用 `codex/rule-compliance-verification`。
PR 描述里贴上第二、三步的正确率对比表。

---

## 六、陷阱速查（详见 `AGENTS.md` §6）

1. 锁残留会让新试验静默失败；第四步 3 局串行，每局结束后确认锁释放再跑下一局。
2. `pkill -f <脚本名>` 会自杀，用 `pgrep -f "[a]ruco_detect_node"`。
3. 大模型偶发返回非法输出不是算法故障，但这次要留意是不是 `single_action_problems`
   过度触发导致重试次数增加、进而增加了偶发超时的概率——如果出现，单独记录。
4. 不要改 `.gitattributes` 里 `deploy/**` 的 `-text` 属性。
5. 加 `--case-ids` 参数时，确认默认行为（不传该参数）和改之前完全一致，
   跑一次全量对比上一轮的 case 列表没有变化。

===== 复制到这里结束 =====
~~~~

---

## 附：本提示词的设计意图（给你，不用发给 Astra）

- **明确砍掉窗口计时这一步，并解释原因**：如果不说清楚"为什么这次不用测窗口"，
  Astra 大概率会延续上一轮的谨慎习惯，重新跑一遍计时验证，浪费服务器时间和她自己的精力。
  第〇节把 2026-10-15 补充分析的论证过程完整复述了一遍，让她能独立判断这个结论是否站得住，
  而不是单纯"被告知不用测"。
- **给了"如果这次抽样过程中又看到窗口偏慢怎么办"的预案**：避免 Astra 在第四步冒烟测试时
  看到个别局 ArUco 耗时偏高，又触发一次不必要的"窗口退化"调查。
- **针对性复测排在全量复测前面，省时间的逻辑和上一版提示词一致**：如果那 4 套仍然大面积
  失败，就不值得跑完整 20 套 × 多次采样。
- **要求往现有共享脚本上加 `--case-ids` 参数，而不是复制一份**：和上一版提示词的"另外复制
  一份、不改原始脚本"不同——这次理由是增加一个可选参数对默认行为零影响，而且这个过滤能力
  未来会反复用到，值得沉淀进共享工具里，不需要每次都复制存档。
