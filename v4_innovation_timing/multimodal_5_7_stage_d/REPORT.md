# FM9G 阶段 D 固定版本回归

## 订正（2026-11-02，发布后发现）

**下面原始结论里的"候选 2/9、基线 3/9"是错的——车道→颜色映射写反了，不是候选表现差。**

本报告最初用固定假设"红色车道 y=+2.1，紫色车道 y=-2.1，蓝色车道 x=5.6"给 actor 编号分配颜色标签（见下方 §0 原文）。但 `judgement.json` 本身就明确标注了
`"reason": "no unique color calibration for this UE instance and roster"`——也就是说这个假设从未针对本次 UE 实例校准过，是我凭经验猜的，而猜错了。

用真实画面直接核验：拉取候选局 `20261101T151020_627988`（红色任务）frame 955 的窗口裁剪图，画面里清清楚楚是一个**真实渲染成红色**的气球，且模型框准确贴住它；该局最终被删除的演员是 `BP_Balloon_C_2147481420`（原表里标成"紫色车道"）。再拉取候选局 `20261101T161631_e7abec`（紫色任务）frame 1144，画面是一个**真实渲染成紫色**的气球，模型框同样贴紧；该局被删除的演员是 `BP_Balloon_C_2147481415`（原表里标成"红色车道"）。两个独立样本都证明：**`2147481415` 实际是紫色气球，`2147481420` 实际是红色气球——和原表完全反过来。**

用修正后的映射重算 18 局（蓝色车道 x=5.6 的映射本身没问题，不受影响）。修复了 `tools/multimodal_5_7_stage_d_analyze.py` 里的 `classify_pos`（红紫互换）后，用同一份原始数据重新跑了一遍官方分析脚本（而不是手工重算），输出见 `evidence/correction_lane_mapping/metrics_corrected.tsv`：

| | 干净命中（删对且只删对） | 命中但多删 | 全程未找到目标 |
|---|---:|---:|---:|
| 候选（9 局） | **7/9** | 1（2 轮蓝色，正确删了蓝色气球，但顺带误删了红色——见 `multimodal_5_11_synthesis/REPORT.md`） | 1（1 轮紫色，全程 `APPROACH=0`） |
| 基线（9 局） | **9/9** | 0 | 0 |

分颜色：红 3/3、紫 2/3（1 次全程未找到）、蓝 2/3 干净命中+1 次命中但多删。候选的真实表现远好于原报告：9 局里 8 局都摧毁了正确颜色的气球（7 局干净、1 局多删），和基线的 9/9 已经很接近，不是"全面落后"。用时、边界事件两项门槛计算不受这次订正影响（它们和颜色标签无关）：边界事件候选 3 次 vs 基线 1 次（允许上限 2 次）仍不通过；额外删球门槛仍因那 1 次误删红色而不通过；"总命中数候选≥基线"按修正后 7（或算上多删那局的话 8）< 9 仍不通过（但差距从"2 vs 3"变成"7-8 vs 9"，性质完全不同）。**结论改为：候选在指定色选择上已经接近基线，按本轮采用门的字面规则仍不通过（1 次误删+1 次全程未找到+边界事件偏多），但不应再被解读为"候选明显比基线差"。两个残留失败的具体机制已在 `multimodal_5_11_synthesis/REPORT.md` 查清：都不是新的感知缺陷。**

下面 §1 起的正文、表格、门槛叙述保持原始未改状态（按 AGENTS.md 的留痕要求），颜色判定请以上面订正后的结论为准，不要再引用原表里的"2/9"。订正证据：`evidence/correction_lane_mapping/`。

---

## 0. 原始结论（已订正，保留存档，不要再引用）

结论：**未通过阶段 D 采用门，候选版本不进入正式比赛部署。** 9 局候选通过飞后 Actor 删除代理判定得到 2/9，封存基线为 3/9；候选的蓝色指定色删除为 2/3，基线为 3/3。候选中有 1/9 局从未进入 `APPROACH`，没有触发“≥6/9 停下等待决定”的特殊条件，但候选的总命中、蓝色命中、额外删球和边界事件门均未通过。服务器最后一行已经切回基线，并用部署指纹复核。

## 实验边界和执行方式

本轮严格使用 `docs/astra-handoff-fm9g-stage-d.md` 的 9+9 矩阵：每色 3 局，候选先跑、基线后跑，颜色顺序为 red → purple → blue，三轮共 18 局；每行在切换条件后完整重启 UE/ROS。候选运行时只加载 FM9G 运行时和固定的目标跟踪插件，没有在候选链路加入 YOLO、HSV、颜色阈值、UE 真值或 `/objects`。

每局飞前要求对象列表为 3 个。飞行和观测器结束后才执行一次 `obj gc`，随后采集 `after/late15/late45/late90/settled` 五个对象列表，并在 settled 后查询存活演员位置。飞前和飞行中没有载荷请求。18 局的 `before_count` 全部为 3，`gc_rc` 全部为 0；18 局都有 `scene_snapshots.jsonl`、`actor_positions.json`、`observer.out` 和日志 SHA256。`trial_rc` 是正式运行器的返回码，不作为命中判据：17 局为 2，第三轮红色基线为 1，但这些行都生成了完整的飞后证据和对象判定。

Actor 颜色只按固定车道位置映射：红色车道 `y=+2.1`，紫色车道 `y=-2.1`，蓝色车道 `x=5.6`。蓝色判定优先于 y 车道判定，因为蓝色边缘车道可能穿过 `y≈±2.1`。若 settled 后恰好少一个演员，则缺失车道是删除目标；少两个记为 `extra_deletion`；没有删除记为 `no_deletion`。

## 逐局结果

`hit/removed` 中的分子是指定色命中，分母是删除演员数量；`first_align_s` 是从观测器 `start_time` 到首次 `Aligned!` 的秒数；`search_s` 按连续 `Position-held search` 日志的时间戳累计；候选的 `model_n/med/p90` 来自对应 FM9G audit.jsonl 的 `presence_model_call.latency_s`，基线没有模型调用。

| 轮 | 色 | 条件 | Actor 判定 | 命中/删除 | APPROACH 次数 | first_align_s | search_s | 总用时(s) | 边界 | model_n | med(s) | p90(s) | rc |
|---:|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 1 | red | candidate | wrong_lane | 0/1 | 10 | 86.891 | 36.213 | 126.638 | 否 | 123 | 0.262949 | 0.513881 | 2 |
| 1 | red | baseline | wrong_lane | 0/1 | 8 | 72.867 | 43.224 | 122.194 | 否 | — | — | — | 2 |
| 1 | purple | candidate | no_deletion | 0/0 | 0 | — | 39.255 | 135.935 | 否 | 115 | 0.262209 | 0.551456 | 2 |
| 1 | purple | baseline | wrong_lane | 0/1 | 3 | 72.612 | 35.206 | 132.216 | 否 | — | — | — | 2 |
| 1 | blue | candidate | hit | 1/1 | 7 | 72.003 | 45.947 | 155.139 | 是 | 124 | 0.260569 | 0.558690 | 2 |
| 1 | blue | baseline | hit | 1/1 | 0 | — | 0.000 | 95.013 | 否 | — | — | — | 2 |
| 2 | red | candidate | wrong_lane | 0/1 | 5 | 81.786 | 46.325 | 130.475 | 否 | 139 | 0.256250 | 0.274714 | 2 |
| 2 | red | baseline | wrong_lane | 0/1 | 5 | 77.031 | 45.262 | 126.738 | 否 | — | — | — | 2 |
| 2 | purple | candidate | wrong_lane | 0/1 | 8 | 104.691 | 36.187 | 130.630 | 是 | 116 | 0.268045 | 0.518828 | 2 |
| 2 | purple | baseline | wrong_lane | 0/1 | 8 | 84.397 | 11.069 | 109.234 | 是 | — | — | — | 2 |
| 2 | blue | candidate | extra_deletion | 0/2 | 12 | 110.951 | 38.213 | 154.155 | 是 | 120 | 0.263831 | 0.513901 | 2 |
| 2 | blue | baseline | hit | 1/1 | 5 | 72.852 | 3.017 | 91.436 | 否 | — | — | — | 2 |
| 3 | red | candidate | wrong_lane | 0/1 | 12 | 81.229 | 42.212 | 125.757 | 否 | 135 | 0.266562 | 0.285327 | 2 |
| 3 | red | baseline | wrong_lane | 0/1 | 5 | 89.212 | 39.186 | 136.584 | 否 | — | — | — | 2 |
| 3 | purple | candidate | wrong_lane | 0/1 | 3 | 80.144 | 22.900 | 126.553 | 否 | 96 | 0.274562 | 0.529814 | 2 |
| 3 | purple | baseline | wrong_lane | 0/1 | 11 | 78.303 | 41.194 | 135.590 | 否 | — | — | — | 2 |
| 3 | blue | candidate | hit | 1/1 | 5 | 77.227 | 45.176 | 143.287 | 否 | 133 | 0.265961 | 0.564975 | 2 |
| 3 | blue | baseline | hit | 1/1 | 5 | 85.499 | 2.008 | 110.541 | 否 | — | — | — | 2 |

完整机器表在 [evidence/metrics.tsv](evidence/metrics.tsv)，其中还保留了 `Aligned!` 墙钟时间、`SPRINT_START/END`、审计目录、原始 rosout 路径以及每局 `mission_success`。

## 门槛计算

- 分颜色：red 候选 `0/3`，基线 `0/3`，通过；purple 候选 `0/3`，基线 `0/3`，通过；blue 候选 `2/3`，基线 `3/3`，**失败**。
- 总删除：候选 `2/9`，基线 `3/9`，且候选低于最低 `3/9`，**失败**。
- 用时中位数：候选 `130.630 s`，基线 `122.194 s`，增量 `8.436 s`；门槛为 `max(10 s, 10%×122.194)=12.219 s`，通过。
- 额外删球：候选 `1`（第二轮蓝色），基线 `0`，**失败**。
- 边界事件：候选 `3`，基线 `1`；允许上限 `1+1=2`，**失败**。
- 审计链：候选 9/9 的 audit.jsonl 都有 `processor_input → ... → closed`，行数 925–1216；每局的对象快照、位置查询、observer 和日志 SHA256 均存在。基线没有 FM9G audit，这是预期的封存条件；其 9 局仍有完整 observer/对象/位置/哈希证据。

候选 9 局中仅 1 局从未进入 `APPROACH`（第一轮紫色），不满足“≥6 局则停下等待用户决定”的单独条件。正确删除的候选 2 局都在删除前出现过 `APPROACH`，因此闭环接近命中为 **2/2**；基线 3 个删除中 2 个出现过 `APPROACH`，闭环接近命中为 **2/3**，第一轮蓝色基线虽然删除了蓝球，但没有 `APPROACH` 日志，不能把它归为闭环接近。候选的失败主要是指定色不匹配、无删除或多删，而不是简单的“模型完全没有输出”：9/9 候选都有 `MULTIMODAL_PIXEL`（每局 27–216 条）和完整 presence model call 审计。

## 部署和回滚核对

候选每局的实际加载指纹为 mission `de03cd1a5687f7bc0664ea52f3cd095f`、bt_ros 源码 `9a1e8d2a5913968b1c2300cad1dc02f7`、插件 `2a2e1b7fc0b2ca37291ecbef97ade06f`、bt_ros 二进制 `1f1592dc8d33613bf4b772a4eb2f6dfb`、FM9G runtime `5026dcf152790e962b11ebee577fb792`。基线每局为 mission `fca24bf1142ca8cddfb9e8d39c387a43`、bt_ros `9b1cefe9dfa431418435f7f8f63a60ed`、二进制 `abb5c49eb21b1b333d88677def4921ab`，没有 multimodal 插件。两种条件的 VisualServo、header、launch 和安全边界 guard 指纹相同。

矩阵结束后服务器状态由 `/home/ubuntu/tcei_baseline_tools/results/stage_d_20261101_retry/status_p3_baseline_blue.json` 复核为 baseline。切换包及元数据备份位置记录在 [evidence/deployment_manifest.json](evidence/deployment_manifest.json)。若需重新恢复候选，只能通过带 md5 校验的 `switch_condition_v2.sh candidate /home/ubuntu/multimodal_v2_backup_20261026T0009 no-reset`，不能直接覆盖正式版本。

## 证据和已知异常

- `evidence/session_p*` 保存每局原始 `scene_snapshots.jsonl`、`actor_positions.json`、五次快照输出、`post_gc.out`、`status.txt`、`sha256.txt`；`evidence/formal_raw/` 保存 18 局的 observer、mission_once、planning、runner、judgement 和对象原始文件。完整正式日志仍保留在服务器对应的 `trial_dir`，路径见 `evidence/metrics.tsv` 的 `raw_log`。
- 矩阵前曾有一条错误 SDK 路径造成的候选红色工具故障（`/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261101T225721_red_A0`）：赛后 GC 返回失败，未计入 9+9；之后修正为 `/home/ubuntu/PX4PSP/RflySimAPIs/RflySimSDK/ue`，重跑的 18 行全部 `gc_rc=0`。该失败没有被删除，属于矩阵前置工具故障记录。
- 运行器的非零 `trial_rc` 和观测器的 `mission_success=false` 只作为运行状态记录，命中统一由 settled Actor 删除代理判定。一个基线紫色局报告 `mission_success=true`，但 Actor 代理仍判为错误车道，说明两者不能混用。

因此本阶段的研究结论是：固定候选版本在真实闭环样本上能够产生可审计的视觉输出，并有 2 次闭环接近命中，但没有达到基线和最低命中门槛，且存在一局多删与更多边界事件。当前不应接入正式比赛；后续若继续研究，应先针对指定色选择和 APPROACH 后的目标保持/多删问题设计新实验，不得把本轮结果解释为“没有视觉输出”。
