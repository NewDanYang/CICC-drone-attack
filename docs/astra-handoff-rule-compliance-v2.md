# Astra 交接提示词：规则合规候选 v2 上机验证（干净计时 + 新措辞回归）

> **使用方式**：把下面 `=====` 之间的全部内容整段复制发给 Astra。
> 起点是分支 `codex/rule-compliance-verification`（已推送 origin，含 commit `e8c9f44`，
> 尚未合入 main，尚未上机）。这是对 2026-10-14 那轮上机验证的后续，不是从头再来——
> 读完 `v3_stability/reports/rule_compliance_20261014/REPORT.md` 和本提示词第〇、一节
> 再动手，不要重新发现已经发现的事。
> 外层用 4 个波浪号包裹，是为了让内层 ```bash 代码块在预览里正常显示。

---

~~~~
===== 从这里开始复制 =====

# 任务：上机验证规则合规候选 v2——先排除测量工具污染，再测新措辞修复是否生效

你在一个真实比赛项目上接手第二轮上机验证。第一轮（2026-10-14）由你自己做完并已回滚，
产出的证据扎实、结论诚实，这次不是推翻那轮工作，而是针对那轮暴露出的两个问题继续往前走。
先读完本提示词，再读 `v3_stability/reports/rule_compliance_20261014/REPORT.md`
和 `v3_stability/rule_compliance/README.md`，再动手。

先读仓库根目录 `AGENTS.md`（环境、已排除结论、已知陷阱、报告规范）。

---

## 〇、上一轮发现了什么，这一轮要解决什么

**上一轮（2026-10-14）你做的两件事：**

1. **部署并上机验证规则合规候选**（窗口默认开+主线程绘制、大模型发布兜底）。
   结论是**回滚**，理由是红色首局 ArUco `ENABLED→DISABLED` 耗时 0.561 s，
   比 2026-10-13 基线 9 局的最大值 0.217 s 高 2.59 倍，触发了"明显变慢即回滚"的判据。
2. **大模型新措辞测试**，20 套指令各采样 3 次，严格正确率 31/54 = 57.4%，
   发现两类 100% 可复现的失败：
   - `blue_ball`（"撞破蓝色球。"）、`red_yanse`（"撞破红颜色的气球。"）、
     `distractor_color`（"不要碰蓝色气球，扎破红色的气球。"）三套，**9/9 次**
     模型吐出完整六步任务而不是一条 `hit_balloon:<色>`；颜色本身是对的，
     所以旧版校验判定"合格"、原样发布——这是旧版校验完全没覆盖的盲区。
   - `step_land`（"返回起点并降落。"）**3/3 次**多输出一条 `return_cross_frame`。

**这一轮要做的两件事，对应这两个问题：**

1. **ArUco 窗口那条"退化"证据本身可能不可信**。你在 `COMPARISON.md` 里自己写了：
   截图脚本 `capture_windows.sh` 在**同一个 X display 上每 2 秒跑一次
   `wmctrl + xwd + ffmpeg`**，和被测的 ArUco 窗口抢同一份资源。0.561 s 到底是窗口代码本身
   变慢，还是截图脚本把它拖慢的，**上一轮的数据区分不出来**。这一轮要把这两件事分开测。
2. **针对那两类必现失败，已经做了第二版候选**（`mission_prompt.txt` 加了 3 条范例，
   `mission_once.py` 加了 `single_action_problems()` 校验），这一轮要验证它是否真的有效。

这两件事都基于**同一批新代码**（commit `e8c9f44`），所以合并成一次上机流程，不要分两次部署。

---

## 一、授权与纪律（和上一轮一致，不重复展开）

直接做、事后报告：SSH 读写服务器文件、部署这四个文件、重启仿真环境、跑正式试验、
清理确认已死的锁、在服务器上新建 `tools/` 下的测试脚本。**只改
`v3_stability/rule_compliance/` 和 `v3_stability/reports/` 下的内容**。

需要先问的只有：改比赛规则禁止项、改安全边界默认值、推送到 `main`、删除别人的实验数据。

纪律：单局成功不是证据；给出数字、样本数、反例；禁止"应该可以""看起来正常"；
**这次尤其要注意区分"测量工具的噪声"和"代码本身的问题"**——上一轮的教训就是没分清这个。

---

## 二、前置检查

```bash
export TCEI_HOST=120.209.70.195 TCEI_PORT=30316 TCEI_USER=root
export TCEI_PASSWORD='<向项目负责人索取，不要写进任何会提交的文件>'
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh "echo OK"
```

端口连接被拒绝 = 云主机关机，找有 gpufree.cn 控制台权限的人，SSH 解决不了。

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

**先确认服务器当前状态**。你上一轮执行过回滚，这一轮的部署脚本会核对线上 MD5，
预期服务器应该处于"已回滚"状态（`mission_once.py` 是 `4b0ae381...`）。核对一下：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'md5sum /home/ubuntu/model/mission_once.py /home/ubuntu/model/prompts/mission_prompt.txt \
   /home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py \
   /home/ubuntu/catkin_ws/src/object_det/scripts/det_color.py'
```
期望值：
| 文件 | 期望 MD5 |
|---|---|
| `mission_once.py` | `4b0ae381b683b7c38d30baf808ed1346` |
| `prompts/mission_prompt.txt` | `321f9b78eb3ad477172f37c70d8b921f` |
| `aruco_detect_node.py` | `0f15e84bdaed68c85d3b6b6ee5e33788`（这个从 2026-10-14 起就没变过，你自己已经回滚过一次） |
| `det_color.py` | `9eda726899abaf4f951f6b03a08c11ad` |

**和期望不符就停下来问**，不要绕过部署脚本的 MD5 检查去强行覆盖——这个检查就是为了防止在
不确定服务器状态的情况下盲目部署。

---

## 三、部署（本次新增 `mission_prompt.txt`，共四个文件）

```bash
for f in mission_once.py mission_prompt.txt aruco_detect_node.py det_color.py deploy_rule_compliance.sh; do
  MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
    v3_stability/rule_compliance/deploy/$f /tmp/rule_compliance/$f
done
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh 'bash /tmp/rule_compliance/deploy_rule_compliance.sh'
```

脚本会：有正式试验锁时拒绝 → 核对四个线上文件的旧 MD5（不符则一个都不改）→
备份到 `/home/ubuntu/rule_compliance_backup_<ts>/` 并生成 `restore.sh` → 复制后再校验新 MD5。
本地已在沙盒中演练过部署/拒绝/回滚三种路径，这次主要是多了一个纯文本文件，没有新的坑，
但仍然要**把脚本的完整输出抄进报告**。

都是文件读取型改动，**不需要 `catkin_make`**，但必须重启仿真环境（含大模型进程）才会生效：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; cd /home/ubuntu/tcei_baseline_tools; setsid nohup bash ./start_sim_environment.sh > /tmp/sim_start.log 2>&1 < /dev/null &'
# 等 2–4 分钟，直到 /tmp/sim_start.log 出现 environment_started=1
```

记下备份路径，回滚命令就是 `bash /home/ubuntu/rule_compliance_backup_<ts>/restore.sh`，
然后重启仿真环境。

---

## 四、验证 A：ArUco 窗口的"干净计时"——这次不许有截图脚本同时跑

**这是本轮最重要的一条，优先级高于验证 B。** 上一轮 0.561 s 那个数字不可信的原因很明确：
截图脚本每 2 秒抢一次 X display。这次的做法是**彻底分离测量和观察**：

### 第一步：3 色 × 3 局，全程不启动任何截图/抓屏脚本
```bash
for c in red purple blue; do
  for i in 1 2 3; do
    MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
      "export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; cd /home/ubuntu/tcei_baseline_tools; \
       setsid nohup bash ./run_formal_trial.sh $c > /tmp/trial_${c}_${i}.log 2>&1 < /dev/null &"
    # 串行：等这一局结束（约 50–300 s）、确认锁已释放，再跑下一局
  done
done
```
**9 局全部串行，不要并发，不要在这 9 局运行期间执行任何 `wmctrl`/`xwd`/`import`/`ffmpeg` 命令，
也不要用 `capture_windows.sh`。** 这是和上一轮唯一的、也是最关键的区别。

对比表，基线见 `v3_stability/hit_balloon_v2/evidence/formal_regression_summary_20261013.csv`
和 `v3_stability/reports/rule_compliance_20261014/baseline/aruco_window_summary_20261012.csv`：

| 指标 | 2026-10-13 基线（9 局） | 2026-10-14 候选（1 局，有截图干扰） | 本次干净计时（9 局） |
|---|---|---|---|
| ArUco `ENABLED→DISABLED` | 0.105–0.217 s | 0.561 s | |
| ArUco 回调 / 解码失败 | 1–2 / 0 | 3 / 0 | |
| 各阶段是否全有 | 全有 | 起飞/穿框/ArUco/逆穿/降落有，击球 observer 未观察 | |
| 总用时 | 115.527–145.325 s | 137.411 s | |
| `boundary_violation_count` | 0–4，7/9 局触发恢复 | 0 | |

**判据**：9 局的 `window_s` 分布如果落在 2026-10-13 的 0.105–0.217 s 区间附近（允许正常波动，
不要求完全一致），就说明上一轮的"退化"确实是截图脚本造成的假信号，窗口代码本身没问题，
**候选可以继续往下走**。如果去掉截图脚本之后仍然明显变慢（比如仍然普遍 >0.3 s），
那说明窗口代码本身确实有问题，这时候才需要回去查 `aruco_detect_node.py` 主线程显示循环
的实现，而不是归咎于截图脚本。

### 第二步：确认没有退化之后，再单独补窗口截图
**不要用轮询脚本**，只在固定时间点截一两张即可：
```bash
# 挑一局飞行过程中，手动在合适时机各截一次（不要用 capture_windows.sh 的 2 秒轮询）
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; import -window root /tmp/win_detection.png'
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; import -window root /tmp/win_aruco.png'
```
**判据**：`Detection + Color` 窗口能看到方框或气球的 bbox；`ArUco Detection (Python)`
窗口在 `detect_aruco` 结束后仍停在屏幕上，标题或画面里有"ID: 35"之类的识别结果。

**如果第一步就发现退化，直接回滚，不要做第二步，也不要做下面的验证 B**——这是上一轮已经
验证过的"退化即回滚"纪律，这次同样适用。

---

## 五、验证 B：新措辞回归——针对性复测 + 全量复测

**只有验证 A 通过（无退化）才做这一节。**

### 第一步：针对性复测上一轮 100% 必现的那 4 套措辞，每套 ≥5 次采样
用 `v3_stability/rule_compliance/tools/llm_paraphrase_probe.py`（这个脚本不用改，
它已经复用线上同一份 `mission_once.py` 的函数，不 publish，不会驱动无人机）。
先确认它能单独跑某几个 case：
```bash
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh \
  'export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority; source /opt/ros/noetic/setup.bash; \
   /opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/llm_paraphrase_probe.py --list-cases'
```
如果脚本目前不支持只跑指定 case（看一下 `--help` 或源码里的参数），
**优先加一个 `--only-case-ids blue_ball,red_yanse,distractor_color,step_land` 之类的过滤参数**
到你自己复制出来的一份脚本副本里，不要改 `tools/` 下的原始副本（那份是上次验证的存档），
新副本放 `v3_stability/reports/rule_compliance_20261015/` 下即可。跑 5 次采样：

```bash
/opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/llm_paraphrase_probe_v2.py \
  --output /tmp/rule_compliance/paraphrase_v2_targeted --samples 5
```

**判据**：这 4 套之前是 9/9、9/9、9/9、3/3 必现失败。这次**至少要有明显改善**——不要求
100% 通过（模型本身有随机性），但如果仍然接近 100% 失败，说明 prompt 范例 + 校验逻辑没有
真正起作用，需要回去看是不是范例写得不够像、或者 `single_action_problems()` 的正则没覆盖到
实际措辞，**不要为了让数字好看而放宽判据**。

### 第二步：全部 20 套复测
```bash
/opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/llm_paraphrase_probe.py \
  --output /tmp/rule_compliance/paraphrase_v2_full --samples 3
```
**判据**：总体严格正确率 ≥95%，样本 ≥40（20 套 × ≥3 次，`area_no_color` 类不计入分母，
和上一轮口径一致）。给出**错误类型分布**，和上一轮的 31/54、7.4%（宽松口径）数字对比，
写清楚具体是哪几类还在失败、失败模式和上一轮是否一致。

**注意**：`mission_once.py` 现在的校验逻辑比上一轮多了一层重试（`single_action_problems`
触发时会带着"只输出用户在这句话里明确要求的动作"的提示重试），所以这次单次生成的耗时
P50/P95 可能会比上一轮略高（上一轮是 2.894 s / 6.155 s）。继续记录耗时，但耗时增加本身
不算失败，除非明显超出比赛现场能接受的等待时间（裁判在旁边等）。

---

## 六、交付物

放在 `v3_stability/reports/rule_compliance_20261015/`：

1. `deploy_log.txt`——部署脚本完整输出 + 备份路径。
2. `timing/`——验证 A 第一步的 9 局对比表 + 原始试验目录名，明确写"退化是否解除"的结论。
3. `windows/`——验证 A 第二步的截图（仅在验证 A 第一步通过后才有）。
4. `llm_paraphrase/targeted/` 和 `llm_paraphrase/full/`——验证 B 两步的 JSONL + CSV + 正确率 +
   错误类型分布，并与上一轮（`v3_stability/reports/rule_compliance_20261014/llm_paraphrase/`）
   逐项对比。
5. `REPORT.md`——一页：
   - 上一轮 0.561 s 那个信号这次有没有解除，解除/未解除的证据分别是什么；
   - 针对性复测和全量复测的正确率，和上一轮的 57.4%/74.1% 对比；
   - 最终结论：继续保留候选、还是回滚、还是需要再改一轮；
   - 回滚命令（无论用没用到都要写）；
   - 结论适用范围——样本数、哪些措辞没覆盖到。
6. 本地离线测试复跑：
   ```bash
   cd v3_stability/rule_compliance
   PYTHONIOENCODING=utf-8 python tests/test_mission_once_fallback.py   # 期望 24/24
   PYTHONIOENCODING=utf-8 python tests/test_aruco_display_loop.py      # 期望 6/6
   ```

发 PR 到 `main`，不要直接推 `main`。分支可以继续用 `codex/rule-compliance-verification`，
或新建 `verify/rule-compliance-v2`。PR 描述里贴上验证 A 的 9 局对比表和验证 B 的正确率对比。

---

## 七、陷阱速查（详见 `AGENTS.md` §6，上一轮你已经踩过大部分坑，这里只列和本轮强相关的）

1. 锁残留会让新试验静默失败；9 局串行，每局结束后确认锁释放再跑下一局。
2. `pkill -f <脚本名>` 会自杀，用 `pgrep -f "[a]ruco_detect_node"`。
3. **这次的核心纪律：验证 A 期间绝对不要跑任何截图/抓屏命令**，哪怕只是手痒看一眼窗口长什么样，
   也等 9 局全部跑完再看。混进去一次就会把这轮数据弄脏，重新论证"退化是否解除"就白做了。
4. 大模型偶发返回非法输出不是算法故障，但这次要留意是不是 `single_action_problems`
   过度触发导致重试次数增加、进而增加了偶发超时的概率——如果出现这种情况，在报告里单独记录。
5. 不要改 `.gitattributes` 里 `deploy/**` 的 `-text` 属性。
6. `tools/llm_paraphrase_probe.py` 原始版本不要改，需要只跑部分 case 时复制一份改。

===== 复制到这里结束 =====
~~~~

---

## 附：本提示词的设计意图（给你，不用发给 Astra）

- **把"验证 A 必须先于验证 B"写成硬顺序**：如果窗口确实退化，后面测新措辞正确率就没有意义——
  候选整体要回滚，纠结措辞修复好不好反而是浪费时间。所以验证 A 不通过直接跳过验证 B。
- **验证 A 的核心是拆分 confound，不是重新主张"没问题"**：提示词没有预设"这次肯定没退化"，
  而是给出可证伪的判据（落在基线区间附近 vs 仍然普遍 >0.3 s），两种结果都写了对应的下一步。
- **验证 B 分两步（针对性 + 全量）是为了省时间**：如果针对性复测那 4 套仍然大面积失败，
  说明 prompt/校验修复本身没生效，不值得浪费时间跑完整 20 套 × 多次采样；只有针对性复测有改善
  才值得做全量复测去对比 95% 门槛。
- **明确禁止为了让数字好看而放宽判据**：这是因为上一轮 Astra 的报告质量很高、如实报告了不达标
  的结果，这次延续同样的纪律要求，避免因为"这次应该修好了"的预期而降低验证标准。
