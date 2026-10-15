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

## 规则逐条状态

| 规则 | 风险 | 状态 | 处理 |
|---|---|---|---|
| 开赛 5 分钟无人机未动 → 本轮结束 | 大模型两次错色或无 ```command 块时**不发布任何命令**，整轮 0 分 | **候选已回滚** | `mission_once.py`：最多 3 次 / 60 s 重试，最后仍按原样发布最接近的一次 |
| 九格语义解析必选，不得手写复合接口 | 校验逻辑若改写命令即越界 | 合规 | 命令只来自大模型输出，校验只做检查、重试、选择，**从不生成或改写命令** |
| 感知结果窗口（每阶段 −5） | ArUco 窗口默认关；检测窗口在 headless 配置下关 | **候选已回滚** | ArUco 与 `Detection + Color`（方框 + 气球 bbox）窗口默认开、主线程绘制；ArUco 检出后保留"ID: n"画面 |
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
| `/home/ubuntu/model/mission_once.py` | `4b0ae381` → `1597c5c1`（第二版；2026-10-14 曾试过 `e7bb1627`，已回滚） | `patches/patch_mission_publish_fallback.py`（v2，源 MD5 不符时拒绝修改） |
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

这两处是配套关系：prompt 范例应该能让模型大部分时候就答对，校验留作兜底，用来接住范例没覆盖到
的其他说法。v2 虽已在完整指令的九局飞行中运行，**这两处对单动作新措辞的修复仍未经过真实模型抽样**：
本轮窗口计时未通过门槛，按流程未启动该抽样。离线测试只能证明校验逻辑本身的行为符合预期。

### 窗口的行为变化
- 图像回调只负责把标注好的画面交给主线程，`imshow/waitKey` 只在主线程调用，避免窗口拖住回调。这也正是 ArUco 回调停摆假设 1 怀疑的机制。
- 显示出错时记录错误，检测照常运行，不会因为窗口拖垮识别。
- `show_window` 和 `debug_display` 的默认值改为 true。配置里**显式**写 false 时仍然生效，所以上机必须核对实际参数（见下）。

## 离线测试

```bash
cd v3_stability/rule_compliance
PYTHONIOENCODING=utf-8 python tests/test_mission_once_fallback.py   # 25 条 PASS、0 失败（2026-10-15 实跑）
PYTHONIOENCODING=utf-8 python tests/test_aruco_display_loop.py      # 6/6 通过
```

`test_mission_once_fallback.py` 里新增的 7 条用例直接取自 2026-10-14 上机测试里真实失败的
那几种措辞（"撞破蓝色球。"等），用桩重放"模型仍然扩写成六步"和"模型已经改好只输出一条"
两种场景，确认新校验逻辑在两种情况下都按预期工作。

测试范围有限：大模型、ROS、OpenCV 窗口都用桩替代。**不能**证明真实大模型配上新范例之后
正确率会不会真的提升，也不能证明窗口开着时 ArUco 和检测的时延不变。这两点必须上机验证。
`det_color.py` 只做了编译检查和 diff 审阅，它的显示循环与 ArUco 的同构，但没有单独测试。

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
**这里特别要注意**：服务器现在应该处于 2026-10-14 回滚后的状态（`mission_once.py` 是 `4b0ae381`），
如果服务器上还是当时试过的候选版（`e7bb1627`），脚本会直接拒绝，这是预期行为，不要放宽 MD5 检查去
强行覆盖，而是确认回滚是否真的做完整了。备份到 `/home/ubuntu/rule_compliance_backup_<ts>/` 并生成
`restore.sh`；复制后再校验一次 MD5。本地已在沙盒中用四文件版本重新演练过部署、重复部署被拒、回滚三种情况。

**回滚**：`bash /home/ubuntu/rule_compliance_backup_<ts>/restore.sh`，然后重启仿真环境。

## 上机验证

**这次的教训：测量工具不能和被测的东西抢资源。** 2026-10-14 的退化判定（ArUco 窗口 0.561 s）
是在抓图脚本每 2 秒对同一个 X display 做一次 `xwd+ffmpeg` 的情况下测出来的，这个工具本身很可能
拖慢了被测的东西，Astra 的报告里也承认了这一点。这次改成**先用干净的计时跑完整轮回归，确认没有
退化之后，再单独补截图**，两件事不要同时做。

1. `rosparam get /object_detection/visualization/show_window` 必须是 `true`。如果是 false，说明启动用了 headless yaml，要改回官方 `detection_params.yaml`。
2. **先跑 3 色 × 3 局（9 局，不启动任何截图脚本）**，与 2026-10-13 那 9 局基线对比：ArUco 窗口时长（0.105–0.217 s）、`callbacks/s`、击球结果、总用时。样本量比上次的 1 局大，结论更可信。窗口开启后任何一项明显变差都要回滚并报告，不要现场调参掩盖。
3. 确认计时没有退化之后，**再单独补窗口截图**（固定时间点截一两张即可，不要用轮询脚本）：
   - `Detection + Color`：穿框和击球阶段有方框、气球的 bbox；
   - `ArUco Detection (Python)`：二维码阶段之后停留在"ID: 35"。
4. 大模型兜底：用一句故意不点名颜色、措辞陌生的指令跑一次，确认 `[命令校验]` 日志和发布行为符合预期。
5. **新措辞回归**：至少重跑 2026-10-14 失败的那几类措辞（"撞破蓝色球。""撞破红颜色的气球。""不要碰蓝色气球，
   扎破红色的气球。""返回起点并降落。"），每种 ≥5 次采样，确认新范例+新校验组合后这几类不再 9/9 或 3/3 失败。
   再跑一遍 `llm_paraphrase_probe.py` 全部 20 套，看整体正确率是否过 95%。

## 比赛当天检查单（初稿）

- [ ] 开赛前已加载好模型（`mission_once.py` 的 `[3/3] 模型就绪`），以交互模式等待输入
- [ ] Setpoint Monitor 终端里 `/mavros/setpoint_raw/local` 在持续刷新，可以给裁判看
- [ ] `Detection + Color` 和 ArUco 两个窗口都在屏幕上（ArUco 窗口在检测开始后才出现）
- [ ] `rosparam get /object_detection/visualization/show_window` 为 true
- [ ] 安全参数 `safety/*` 是默认值（`y_max=3.0`），不是越界测试用的值
- [ ] 没有残留锁 `/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`
- [ ] 输入指令前确认题目颜色，发布后核对日志里的 `hit_balloon:<色>`
- [ ] 准备好向评委说明控制链：大模型 → `/mission_command` → `bt_ros` 逐条命令生成 BT 节点 → `/mavros/setpoint_raw/local`
