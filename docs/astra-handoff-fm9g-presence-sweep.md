# Astra 交接：九格"存在-遮挡扫描"定位接入击球闭环（5.0 → 5.1）

开始前请读完：`AGENTS.md`、`v4_innovation_timing/multimodal_5_0_presence_sweep/REPORT.md`、`v4_innovation_timing/multimodal_3_3/REPORT.md`（分支 `origin/codex/multimodal-32-corrected`）、`v4_innovation_timing/multimodal_3_3/protocol_v2.md`（同分支）。

## 0. 背景（不需要你重新验证）

- 九格回归坐标 token 的路线（3.1–4.1，含全部 LoRA）已经证伪，**不要再训练坐标 LoRA**。
- 新方法只用基座 FM9G4B-V，不加载适配器：把"有没有 X 色气球"的首 token 概率当作信号，经过 15 瓦片粗定位和两遍四向遮挡扫描得到框。单帧 run10 测试 25/30 过门（LoRA 最好 3/30）。9 局真实击球窗口回放：中心正确 63%，发布精确率 88%，获取延迟中位 2.0 s。
- 已知缺陷：CSRT 在目标离开后漂到背景上，放弃太慢；面积被低估（中位 0.65 倍）；目标被立柱遮挡时框停在立柱上。
- 全部代码在 `v4_innovation_timing/multimodal_5_0_presence_sweep/tools/`，服务器副本在 `/root/gpufree-data/fm_research/tools/`，两边字节一致。`fastpresence.py` 是 GPU 快路径，`p10_servo_replay.py` 是离线时序回放评测台。

## 1. 硬约束（违反任一条立即停止并报告）

1. 比赛运行链路里不得出现 YOLO、HSV、颜色阈值、UE 真值或 `/objects` 读取。HSV 和 YOLO 只能出现在离线评分脚本里。
2. 不改 VisualServo（cpp/h）、安全边界、launch 里的速度参数和 `optimization/*`、航点、方向 A/B、用时优化 1/2。
3. 只加载一份模型。命令生成与图像推理共用 `mission_once.py` 里的同一个实例和同一把 `model_lock`。
4. 每个部署文件改动前备份并记录 md5；回滚必须用脚本，并核对实际二进制（参照 3.2 `switch_condition_v2.sh`）。
5. 用服务器前检查 `/tmp/tcei_formal_trial.lock` 和 `baseline_runs.csv` 最后一行；有人在用就停下等。
6. 口令只用环境变量 `TCEI_PASSWORD`，不得写进任何文件或提交。
7. 任何结论都要附样本数、对照组和原始证据路径。失败局不得剔除。

## 2. 阶段 A：离线改进与开发门（不碰仿真，预算 1 天）

在 `p10_servo_replay.py` 的副本 `p11_servo_replay.py` 上实现下面四项改动。**每一项单独开关**，逐项 A/B，全部以 9 局回放（224/224 模式）为准：

| 编号 | 改动 | 具体规则 |
|---|---|---|
| A1 | 快速放弃 | 复核间隔改为 0.25 s；复核窗口为 1.2 倍当前框，最小边 40 px；**一次** `P(是)<0.5` 立即停止发布并回到 SEARCH |
| A2 | 尺寸锁定 | 每次精扫刷新后记录扫描框尺寸 `(w0,h0)`；之后发布的框用 CSRT 中心，尺寸取 `w0×s`、`h0×s`，其中 `s` 是 CSRT 框相对初始化时的边长比，夹在 [0.85, 1.6] |
| A3 | 刷新加频 | 精扫刷新间隔从 2.0 s 改为 1.0 s |
| A4 | 224 阈值重拟合 | 用 `evidence/p8_r224.jsonl` 和 `p7_score.py`，**只用 train split** 重拟合四个阈值，回放时精扫用这组阈值 |

开发门（9 局合计，同时报告每色明细）：

- YOLO 可见帧中心落在 YOLO 框内的比例 ≥ 70%；
- 在 YOLO 可见帧上的发布精确率 ≥ 92%；
- 目标离开画面后（YOLO 连续不可见，且你人工确认确实离开）残留发布：中位 ≤ 2 帧，最大 ≤ 4 帧；
- 获取延迟中位 ≤ 2.0 s；
- 面积比（发布/YOLO）中位落在 [0.8, 1.25]。

注意：9 局都是开发数据，不是盲测，报告里必须写明这一点。人工确认"YOLO 漏检但九格正确"的帧时，要像 `evidence/p10_05.jpg` 那样出联系表存档，不能只凭判断。

**止损**：四项都做完仍有两条以上未达标 → 停止，提交报告，不进入阶段 B。只差一条时，允许把 A1 的复核间隔调到 0.2 s 或 0.35 s 各试一次，不得做其他调参。

## 3. 阶段 B：接入实现（预算 1 天）

以 3.2 第二次实施包为底（仓库分支 `origin/codex/multimodal-32-corrected` 的 `v4_innovation_timing/multimodal_3_2/v2/`，服务器 `/home/ubuntu/multimodal_v2/`）。**保留**：session/epoch 门控、击球阶段关闭 YOLO 门、`MultimodalTargetTracker` C++ 插件、帧龄 ≤0.35 s 检查、主线程窗口显示与截图、全部审计日志、`ReplayTracker` 的回放与超龄逻辑。

**替换** `runtime.py` 的 `inference_loop`：

- 初始化：删除 `OverlapLocalizer`、`local_regions`、`semantic_labels`（以及 GrabCut 残留），改为阶段 A 定稿的"存在监视 → 瓦片 → 两遍扫描"。
- 确认：改为 A1 的裁剪复核。
- 新增：A3 的周期精扫刷新，结果走 `pending`，类型为 `refresh`。由 tracking_loop 用刷新框重新初始化 CSRT，并回放推理期间到达的帧。
- 发布：A2 的尺寸规则。

审计要求：每次调用记录批大小、实际图像张数、耗时、`p0` 和四条扫描曲线。每个决策 ID 都要能串起 源帧 → 框 → `/multimodal/objects` → `MULTIMODAL_PIXEL` → VisualServo `ALIGN/APPROACH err` → `/mavros/setpoint_raw/local`，与 3.2 的 `control_links.json` 格式一致。

离线验收（不起飞）：
(1) 用真实帧逐条核对 FastPresence 与官方 processor 的概率差 ≤ 0.03；
(2) 在服务器上用录制帧通过 rosbag 或回放节点驱动 runtime，结果须与 p11 回放一致：同一帧序列的框中心差中位 ≤ 3 px；
(3) 跑一遍源码审计，确认链路里无 YOLO/HSV。

## 4. 阶段 C：单局台架（预算 0.5 天）

按 `AGENTS.md` §2.3 启动仿真，红色跑 1 局候选。检查四件事：processor 每次调用的图片数正确；窗口截图里框住了红球；VisualServo 消费了像素；服务器 GPU 显存与延迟（同时运行命令生成时的定位耗时，报中位和 P90）。

若出现"0 张图"、"无像素消费"、"模型进程退出"等**实现缺陷**，只修实现、不改算法，最多 2 次；第 3 次仍失败就停止并报告。

## 5. 阶段 D：固定版本回归（预算 1.5 天）

冻结候选的 manifest SHA256，严格按 3.3 `protocol_v2.md` 执行：候选与封存对照各 9 局，每色 3 局，颜色交替配对；每局完整重启 UE；飞后用 Actor 删除代理判定，判定前不得发任何载荷请求或 GC。

采用门（全部满足才算通过）：

1. 每色候选指定色删除数 ≥ 对照；
2. 候选总删除数 ≥ 对照总删除数，且候选至少 3/9；
3. 总用时中位数增量 ≤ max(10 s, 对照中位数的 10%)；
4. 候选额外删球局数 ≤ 对照；边界事件数 ≤ 对照 + 1；
5. 每局都有完整审计链，且至少 1 局能逐条复现"九格框 → 伺服 → 指令"。

不通过：回滚、提交完整报告，不追加调参局。通过：保持部署、提交报告，并单独列出"全类别识别"缺口（方框、起降标识、障碍物仍走旧链）。

## 6. 交付物

- 新目录 `v4_innovation_timing/multimodal_5_1_presence_flight/`，内含 `REPORT.md`、阶段 A 的 A/B 表、全部原始证据（单局包和 SHA256 清单）、部署与回滚脚本、最终部署状态核对 JSON。
- 在新分支 `research/fm9g-presence-flight` 上提交，PR 到 `main`，不要直接推 `main`。
- 报告必须区分三类：算法问题、环境偶发、大模型命令输出异常。

## 7. 遇到这些情况立即停下并报告，不要自行决定

- 任何门槛需要放宽才能通过；
- 需要改 VisualServo、速度参数或航点才能命中；
- 显存不足，需要加载第二份模型或量化；
- 发现 FAQ 或规则与本方案冲突的新证据。
