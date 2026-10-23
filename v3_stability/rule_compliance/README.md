# 规则合规修改（2026-10-13，仿真初赛）

依据：赛事规则原文 3.2、4.1–4.4（`打击.pdf`），以及官方补充 QA 手册 `规则.txt`
（"赛道QA使用手册Preview版"，2026-10-15 读取；二者冲突处以 QA 手册为准，详见下方表格脚注）。
本目录的候选改动已完成离线测试。

> **2026-10-14 更新：候选版曾上机试部署，随后已回滚。** 首局红色 ArUco 窗口
> 0.561 s，高于旧版 9 局的 0.106–0.217 s；因此没有继续紫、蓝局。
> 新措辞严格正确率为 31/54，未达 95%。这三文件已在当轮回滚。
> 原始证据和结论边界见 [`../reports/rule_compliance_20261014/REPORT.md`](../reports/rule_compliance_20261014/REPORT.md)。
>
> **2026-10-15 候选说明：针对该报告里两个可复现 100% 的新措辞失败，做了第二版候选。**
> 0.561 s 那条 ArUco 退化信号本身也有问题——抓图脚本 `capture_windows.sh` 在同一 X display
> 上每 2 秒跑一次 `xwd+ffmpeg`，和被测窗口抢资源，Astra 自己在报告里点破了这个 confound，
> 所以窗口耗时结论其实是**未决**，不是**证伪**。详见下方"下一步"。
> 这一版只改了 `mission_once.py` 和 `mission_prompt.txt`，ArUco/检测窗口的改动不变（MD5 相同）。
>
> **2026-10-15 上机结果：v2 已部署并在九局无抓屏正式试验后回滚。** ArUco 窗口
> 中位数 0.147 s，但 3/9 局达 0.309–0.349 s；旧版九局最大为 0.217 s。
> 识码与降落均 9/9 成功，当时按"窗口无退化"门槛判定未通过，因此按流程没有做
> v2 截图或真实模型新措辞抽样。线上四文件已恢复原 MD5 并重启，原始证据、
> 回滚命令和适用范围见 [`../reports/rule_compliance_20261015/REPORT.md`](../reports/rule_compliance_20261015/REPORT.md)。
>
> **2026-10-15 事后复核：上面那 3/9 局超时，按回调数分层看其实不异常。** 把
> `window_s` 除以 `callbacks`（定位二维码用了几次图像回调）后，这 3 局每次回调
> 耗时 0.103–0.116 s，落在旧版 `callbacks=1` 样本的 0.036–0.155 s 区间内；窗口的
> 主线程绘制改动不参与 ArUco 角点检测，没有机制能让"需要几次回调"这件事变化。
> 旧版 19 条样本从未出现过 `callbacks=3`，更可能是旧版样本量不够、没抽到这种
> 情况。**修正结论：没有证据支持窗口代码本身有处理时延，可以认为无明显退化。**
> 详见 [`callback_count_stratified_analysis.md`](../reports/rule_compliance_20261015/timing/callback_count_stratified_analysis.md)。
> 下一步直接部署这版四文件、跳过重复计时，推进真实模型新措辞抽样（验证 B）。

> **2026-10-15 第三轮实测：验证 B 已完成，候选重新部署并保留在线上。**
> 四个旧版 MD5 核对后按原候选文件部署；真实模型专项 4 类各 5 次，严格 **19/20**，
> 全量 20 类各 3 次，排除无颜色区域类后严格 **52/54 = 96.3%**（上一轮 31/54）。
> 红、紫、蓝各一局端到端冒烟中，非击球五阶段均 3/3 成功；击球 observer 仅蓝色
> 标为成功，红紫未观测。候选可进入合并评估，但否定颜色句的兜底仍有漏掉击球的反例。
> [第三轮报告及原始样本](../reports/rule_compliance_20261015_v3/REPORT.md)。
>
> **2026-10-15 补丁：修复上面那条"漏掉击球"的反例，尚未上机。** 问题出在
> `generate_validated_commands` 的兜底排序只比较未知命令数和问题总数，三次重试若打平
> （如 `distractor_color` 第 1 次：三次都只有一个"疑似多余步骤"的问题），就保留**先出现**
> 的那次——哪怕它完全没有 `hit_balloon` 行，旁边明明有带着正确颜色的答案。新加的
> `balloon_command_missing()` 把"有没有打气球命令"排进第一优先级，键在指令文本本身而不是
> `expected`（`不要碰蓝色气球，扎破红色的气球。`这类指令会让 `expected_balloon_color()`
> 故意返回 None，因为同时点了两种颜色——这正是触发这个 bug 的真实样本）。
> 用 Astra 这次采到的真实失败样本做了回归测试，离线 28/28 通过；`mission_once.py` 新 MD5
> `fca24bf1`（服务器当前应处于 v2 候选状态 `1597c5c1`，部署脚本的"旧 MD5"已相应更新）。
> **未上机验证**——下一步需要真实模型重跑一次 `distractor_color`，确认兜底不再丢掉气球命令。

## 规则逐条状态

| 规则 | 风险 | 状态 | 处理 |
|---|---|---|---|
| 开赛 5 分钟无人机未动 → 本轮结束 | 大模型两次错色或无 ```command 块时**不发布任何命令**，整轮 0 分 | **候选已重新部署；进入合并评估** | `mission_once.py`：最多 3 次 / 60 s 重试，最后仍按原样发布最接近的一次；第三轮有一次兜底漏掉击球 |
| 九格语义解析必选，不得手写复合接口 | 校验逻辑若改写命令即越界 | 合规 | 命令只来自大模型输出，校验只做检查、重试、选择，**从不生成或改写命令** |
| 感知结果窗口（每阶段 −5） | ArUco 窗口默认关；检测窗口在 headless 配置下关 | **候选已重新部署；本轮未重测计时** | ArUco 与 `Detection + Color`（方框 + 气球 bbox）窗口默认开、主线程绘制；ArUco 检出后保留"ID: n"画面 |
| 降落标志检测窗口 / 视觉反馈 | 降落完全没有感知 | **未修** | 第二部分：降落标志检测 + 窗口 + 视觉对准 |
| 禁止预设位置点（审查后每阶段 −5） | BT 中的固定坐标；红区 yaw=π、接近高度 1.5 是新增预设 | **未修** | 第一部分改红区为感知扫描定向；第二部分准备审查说明 |
| 碰撞 −10（一次性，见脚注¹） | 9 局中 7 局击球后触发边界恢复；红、蓝区共用击球点，有误击风险 | **未修** | 第一部分：接触后刹车，三球全在场时零误击 |
| 赛前 `rostopic echo /mavros/setpoint_raw/local` 展示 | — | 合规 | `sim_env_start.sh` 已开 Setpoint Monitor 终端，见检查单 |
| 禁止改仿真速度 | — | 合规 | 未改动 |
| 10 分钟限时；计时到电机停转 | — | 合规 | 正式试验 ≤300 s；降落 9/9 解除武装 |
| 两次演示机会，取较高分 | — | 合规 | 无需代码改动；`规则.txt` FAQ 5.4 已确认"取两次演示中成绩较高的一次"，之前"仅限时间允许"的说法已过时 |
| 指令只能逐条手输，不得脚本一键发送 | — | 合规 | `mission_once.py` 本就是交互式单行输入循环（`规则.txt`："所有提示词只能一步步输入执行，不能用脚本一键执行完毕"） |

¹ 原先按 `打击.pdf` 记的是"每物体 −5"；2026-10-15 读到的官方 QA 手册 FAQ 5.7（打击赛专条）写的是
"碰到都会扣分，但只扣一次；只要碰撞一次就扣 10 分，扣完之后后面再碰就不扣了"，口径更晚、也更明确，
以此为准。但扣分范围是"整场一次"还是"每阶段一次"仍不清楚，按更保守的"整场一次"处理。

## 改动内容

| 文件 | 原 MD5 → 新 MD5 | 生成方式 |
|---|---|---|
| `/home/ubuntu/model/mission_once.py` | `1597c5c1` → `fca24bf1`（第三版，未上机；`1597c5c1` 是当前线上版本，`4b0ae381` 是最初基线，2026-10-14 曾试过的 `e7bb1627` 已回滚） | `patches/patch_mission_publish_fallback.py`（v3，源 MD5 不符时拒绝修改） |
| `/home/ubuntu/model/prompts/mission_prompt.txt` | `321f9b78` → `204b9124`（新增，2026-10-15） | `patches/patch_mission_prompt_paraphrase_examples.py`（源 MD5 不符时拒绝修改；保留原文件的 CRLF 字节） |
| `catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py` | `0f15e84b` → `43c3bc40` | 本 PR 以 `deploy/aruco_detect_node.py` 作为已核对的候选 payload；旧版由服务器回滚备份保存；**这版没有改动** |
| `catkin_ws/src/object_det/scripts/det_color.py` | `9eda7268` → `348dd7d0` | `patches/patch_det_color_window.py`（源 MD5 不符时拒绝修改）；**这版没有改动** |

`mission_prompt.txt` 是纯文本，其余三个是 Python 文件，**都不需要 catkin_make**，但要重启节点
（大模型进程读提示词文件也只在启动时读一次，改完同样要重启）。

### `mission_once.py` 的行为变化
- 每次回答都检查四项：有没有 ```command 块；命令名是否都属于 `takeoff/cross_frame/detect_aruco/return_cross_frame/hit_balloon:<red|purple|blue>/land`；指令里只点名一种颜色时，`hit_balloon` 是否恰好是这个颜色；**（v2 新增）指令只提到气球或只提到降落这一个阶段时，输出是否恰好只有这一条命令**。
- 颜色识别扩展到"红色气球、红色的气球、红颜色的气球、红气球、red balloon"。指令里出现两种颜色（例如"不要碰蓝色，扎破红色"）时不做颜色校验。
- 不合格就带提示重试。`MISSION_MAX_ATTEMPTS`（默认 3）和 `MISSION_RETRY_BUDGET_S`（默认 60）都可以通过环境变量调整。
- 都不合格时，发布未知命令最少的那次回答，**原样发布**。宁可只丢气球阶段 25 分，也不因无人机不动而丢掉整轮。
- 一次 ```command 块都拿不到时仍然不发布，因为我们不能自己编命令。这种情况会打日志，需要操作员重新输入指令。

### v2 新增：单动作指令被扩写成全流程（2026-10-15）
2026-10-14 上机测的 20 套新措辞里，发现 v1 完全没覆盖的一类真实 bug（原始数据见
[`../reports/rule_compliance_20261014/llm_paraphrase/samples.jsonl`](../reports/rule_compliance_20261014/llm_paraphrase/samples.jsonl)）：
- "撞破蓝色球。"、"撞破红颜色的气球。"、"不要碰蓝色气球，扎破红色的气球。"——这三种措辞 **9/9 次**
  让模型吐出完整六步任务，而不是只输出一条 `hit_balloon:<色>`。因为六步里的颜色恰好是对的，
  v1 的颜色校验会直接判定"合格"、原样发布。
- "返回起点并降落。"——**3/3 次**多输出一条 `return_cross_frame`，变成"穿回方框再降落"。

两处修复配套使用：
1. `mission_prompt.txt` 补了 3 条针对性范例（上面三种措辞各一个变体 + 单独的"返回起点并降落"），
   让模型有同族的单动作范例可以模仿，而不是只有一个"六步全流程"的复杂范例。
2. `mission_once.py` 加了 `single_action_problems()`：只在指令**只提到气球、不提其他阶段**，
   或**只提到降落、不提其他阶段**时才检查步数是否恰好是一条；真正的多步指令（同时提到气球和其他
   阶段）不会被误判。判据故意写得很窄，避免把合法的多步指令当成错误拦下来。

这两处是配套关系：prompt 范例让模型大部分时候答对，校验留作兜底。
第三轮真实模型专项抽样 **19/20**，全量严格 **52/54**；仍有一次否定颜色句三次重试后
兜底选择了不含击球的命令，另有两次无 `command` 标签代码块被线上校验接受、在严格判据下失败。
详见[第三轮报告](../reports/rule_compliance_20261015_v3/REPORT.md)。

### v3 新增：兜底排序会丢掉本来存在的正确击球命令（2026-10-15，已部署；线上兜底分支未触发）
第三轮真实模型抽样里，`distractor_color`（"不要碰蓝色气球，扎破红色的气球。"）第 1 次采样
三次重试依次是：
1. `detect_aruco\nland`（**完全没有 `hit_balloon`**）
2. `takeoff\ndetect_aruco\nreturn_cross_frame\nhit_balloon:red\nland`
3. `takeoff\nhit_balloon:red\nland`

三次都被 `single_action_problems()` 判定"疑似多余步骤"，问题个数打平，旧版排序 `(未知命令数,
问题总数)` 全部是 `(0, 1)`，三者相等时保留**先出现**的一次——于是发布了完全没打气球的第 1 次，
第 2、3 次明明带着正确颜色却被扔掉。这个指令点了两种颜色，`expected_balloon_color()` 按设计
返回 `None`（不强行指定颜色），所以这个 bug 和 `expected` 是不是已知颜色无关。

新加的 `balloon_command_missing()` 直接查**指令文本本身**（不依赖 `expected`）是不是在说打气球，
是的话把"有没有打气球命令"排进排序的第一位：没有任何 `hit_balloon` 行的答案，一定排在有的
后面，不管后者还带着多少多余步骤——多余步骤顶多让飞机多绕几步，完全没打气球命令则是确定丢掉
整个 25 分阶段。离线回归测试直接用了上面这组真实失败样本，确认新排序会选中第 2 或第 3 次答案。

修复已部署。真实模型对 `distractor_color` 连续采样 8 次并追加 16 次，最终命令均含
`hit_balloon:red`（24/24）；这 24 次都只有一次生成，未触发兜底排序。因此当前能确认该措辞
在本次样本中正确，**不能声称线上兜底路径已经通过触发式验收**。离线真实失败样本重放仍为
28/28；原始采样与局限见[上机复核报告](../reports/rule_compliance_20261015_v3b/REPORT.md)。

### 窗口的行为变化
- 图像回调只负责把标注好的画面交给主线程，`imshow/waitKey` 只在主线程调用，避免窗口拖住回调。这也正是 ArUco 回调停摆假设 1 怀疑的机制。
- 显示出错时记录错误，检测照常运行，不会因为窗口拖垮识别。
- `show_window` 和 `debug_display` 的默认值改为 true。配置里**显式**写 false 时仍然生效，所以上机必须核对实际参数（见下）。

## 离线测试

```bash
cd v3_stability/rule_compliance
PYTHONIOENCODING=utf-8 python tests/test_mission_once_fallback.py   # 28 条 PASS、0 失败（2026-10-15 实跑，含 v3 回归）
PYTHONIOENCODING=utf-8 python tests/test_aruco_display_loop.py      # 6/6 通过
```

`test_mission_once_fallback.py` 里有两批取自真实上机失败样本的回归用例：7 条来自
2026-10-14 的措辞过度生成问题，3 条来自 2026-10-15 真实模型抽样时发现的兜底排序
bug（直接用 `distractor_color` 第 1 次的三次真实重试内容构造，见上面的 v3 小节）。

测试范围有限：大模型、ROS、OpenCV 窗口都用桩替代，**不能**替代真实上机结果。
窗口计时和 v2 新措辞修复已经分别经过上机验证；v3 兜底排序修复虽已部署和真实模型重采样，
但没有产生多轮重试，因而尚无线上兜底路径的直接观测。`det_color.py` 只做了编译检查和 diff 审阅。

## 部署（服务器开机、确认无人使用后）

```bash
# 本地
for f in mission_once.py mission_prompt.txt aruco_detect_node.py det_color.py deploy_rule_compliance.sh; do
  MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
    v3_stability/rule_compliance/deploy/$f /tmp/rule_compliance/$f
done
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh 'bash /tmp/rule_compliance/deploy_rule_compliance.sh'
# 然后按 AGENTS.md §2.3 重启仿真环境
```

脚本会做这些检查：有正式试验锁时拒绝；四个线上文件的 MD5 必须与上表"原 MD5"一致，否则一个都不改——
**这里特别要注意**：服务器现在应该处于 2026-10-15 第三轮验证后的 v2 候选状态
（`mission_once.py` 是 `1597c5c1`，其余三文件和候选值一致），因为那一轮的处理决定是
"保留候选部署"，没有回滚。如果服务器状态和预期不符，脚本会直接拒绝，这是预期行为，
不要放宽 MD5 检查去强行覆盖，而是先确认服务器实际处于哪个状态。备份到
`/home/ubuntu/rule_compliance_backup_<ts>/` 并生成 `restore.sh`（会退回到 v2 候选状态，
不是最初的基线）；复制后再校验一次 MD5。本地已在沙盒中用"v2 候选 + v3 更新"的组合
重新演练过部署、重复部署被拒、回滚三种情况。

**回滚**：`bash /home/ubuntu/rule_compliance_backup_<ts>/restore.sh`，然后重启仿真环境。

## 上机验证进度

| 验证项 | 状态 | 证据 |
|---|---|---|
| ArUco/检测窗口是否退化 | **已解决（无明显退化）** | [2026-10-15 事后复核](../reports/rule_compliance_20261015/timing/callback_count_stratified_analysis.md)，按回调数分层后 3 局偏慢样本落在正常区间 |
| 大模型新措辞（v2 修复：prompt 范例 + 单动作校验） | **已上机验证通过** | [第三轮报告](../reports/rule_compliance_20261015_v3/REPORT.md)：专项 19/20，全量 52/54=96.3% |
| 兜底排序修复（v3：`balloon_command_missing`） | **已部署、未触发兜底路径** | [复核报告](../reports/rule_compliance_20261015_v3b/REPORT.md)：真实模型 24/24 含正确击球命令，0/24 发生重试；离线重放 28/28 |
| 端到端冒烟（3 色各 1 局） | 部分完成 | 非击球五阶段 3/3 成功；击球 observer 判据本身有局限（缺场景 Actor 颜色校准），红、紫两局未观测 |

**下一步**：
1. 若真实运行再次出现多轮重试，记录完整候选与最终选择，直接验证兜底排序路径；不要用
   24 次单轮成功样本替代这项证据。
2. 复查上一轮报告里两个 `no_command_block` 的"失败"是不是真的需要处理——目前的解读是
   探针判据比线上真实逻辑更严（真实 `generate_commands()` 不要求 ```command 标签），
   如果认同这个解读，这两个不需要再修代码，但探针本身的判据可以考虑放松，使其更贴近线上行为。

## 比赛当天检查单（初稿）

- [ ] 开赛前已加载好模型（`mission_once.py` 的 `[3/3] 模型就绪`），以交互模式等待输入
- [ ] Setpoint Monitor 终端里 `/mavros/setpoint_raw/local` 在持续刷新，可以给裁判看
- [ ] `Detection + Color` 和 ArUco 两个窗口都在屏幕上（ArUco 窗口在检测开始后才出现）
- [ ] `rosparam get /object_detection/visualization/show_window` 为 true
- [ ] 安全参数 `safety/*` 是默认值（`y_max=3.0`），不是越界测试用的值
- [ ] 没有残留锁 `/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`
- [ ] 输入指令前确认题目颜色，发布后核对日志里的 `hit_balloon:<色>`
- [ ] 准备好向评委说明控制链：大模型 → `/mission_command` → `bt_ros` 逐条命令生成 BT 节点 → `/mavros/setpoint_raw/local`
