# FM9G4B-V 空间定位实验（4.0）

复核时间：2026-10-30（北京时间）。本分支包含两轮真实图像训练、两组独立推理评估和一轮仅用验证集拟合的后处理审计。模型适配器没有接入正式比赛系统，也没有修改飞行逻辑或速度参数。

## 结论

这次实验支持一个有限但清晰的结论：**增加独立采集轮次并保持颜色标签一致，能改善未见图像上的坐标误差，但当前 LoRA 仍没有形成可部署的稳定几何定位能力。**

第一轮把旧的 run3/run7 训练行按像素色相清洗，使用修正后的 MLA LoRA 配置和原生 `<box>` 输出。run10 独立测试为 1/30 几何通过，中位中心误差 48.15 px。第二轮将独立 run8 的 28 条真实行加入训练，run9 的 17 条经检测框和像素色相双重审计的真实正例作为验证，run10 仍完全留出；测试提升到 3/30，红 2/10、紫 1/10、蓝 0/10，中位中心误差 34.14 px，负例误报 0/12。提升是真实的，但仍远低于可接入门槛。

因此当前候选**不值得接入比赛运行时**。它可作为赛后继续研究的初始化适配器和数据清洗基线；比赛前剩余时间应投入主流程稳定性。

## 两极分化诊断

3.9 的 20 张自检图逐张查看了原始 PNG、标签框、完整 `<box>` 输出、框内色相和同图的其他颜色行。5 个失败不是单一的坐标格式问题：3 个紫色失败的框实际覆盖红球，且部分与同图 red 框重叠；`run7_00478_red` 是清晰红球上的同图红/紫冲突；`run3_00035_blue` 是真实可见小蓝球的中心/尺寸回归失败。5 个原始输出都能解析为规整的 `<box>`，没有 JSON 或解码格式异常。

同一批图的 image processor 审计显示，成功和失败样本全部使用相同的 640×480→518×392 全局图、`[2,1]` adaptive grid 和 2 张切片；坐标审计也确认 y 轴按 480/1000 还原，没有“y 坐标约两倍”的实现错误。故本轮没有重复分块或坐标单位假设。

## 数据集与审计

第一轮 `mm40_spatial_clean`：训练 110 条（76 张唯一训练图，31 红、9 紫、34 蓝正例和 36 负例），验证 28 条来自 run8，测试 42 条来自 run10。训练集中 11 条色相不匹配紫球行、6 条跨色重叠行被剔除；具体拒绝原因和色相比例写入服务器构建收据。

第二轮 `mm41_run8_mix`：在第一轮训练上加入 run8 的 28 条真实行，训练增至 138 条、94 张唯一图；验证改用 run9 的 17 条正例（红 14、紫 2、蓝 1），测试仍为 run10 的 42 条。run9 行来自真实 RGB 采集事件，使用 `/objects` 提议框后按速度≤0.35 m/s、目标类别和框内 HSV 色相≥0.25 审计；它们没有被当成最终盲测。run9 验证没有负例，所以它只承担定位误差监控，不能承担负例门判断。

原始数据收据、可复现 JSON 和拒绝清单在：

- [`mm40 receipt`](evidence/mm40/receipt.json)
- [`mm41 receipt`](evidence/mm41/receipt.json)
- [`mm40 cases`](evidence/mm40/cases.json)
- [`mm41 cases`](evidence/mm41/cases.json)
- [`run9 pixel audit`](evidence/mm41/run9_audit.json)

本次尝试重新启动仿真环境时，SITL/RflySim3D 启动但 MAVROS 未报告 `connected=true`，因此没有把一个未确认的采集轮次冒充新数据；启动证据保存在 [`sim_start_astra.log`](evidence/sim_start_astra.log)。本报告使用的新增训练信号来自已有真实 run9 采集帧，并明确标注其来源。

## 训练配置

两轮都使用 3.8 修复后的配置：真实存在的五类 MLA 投影模块、`modules_to_save=None`、视觉侧冻结、语言侧冻结、BF16、CPU optimizer offload、LoRA `r=64/alpha=64/dropout=0.05`，学习率 `5e-5`。训练输出统一为模型原生 `<box>x1 y1 x2 y2</box>`，坐标按当前图片宽高归一化到 0–1000；评估使用同一中文提示词和确定性解码。

第一轮 1200 步，验证 loss 最低点是 step 200（0.8341），适配器 SHA-256 为 `073c44274e292a643bb84b0bd74feb37c8033d7068bf88a4d37db39d9afb9711`。第二轮 600 步，验证 loss 最低点是 step 200（0.8609），适配器 SHA-256 为 `f25c8170050c36762eef3bdbe70ab38e12033e1e4373b613a51e6b277d61c43b`。两份适配器均留在服务器：

```text
/root/gpufree-data/mm40_spatial_clean/output_lora
/root/gpufree-data/mm41_run8_mix/output_lora
```

训练状态、可训练参数审计和逐步验证 loss 在 [`mm40 trainer_state`](evidence/mm40/trainer_state.json)、[`mm40 trainable`](evidence/mm40/trainable_parameters.json)、[`mm41 trainer_state`](evidence/mm41/trainer_state.json)、[`mm41 trainable`](evidence/mm41/trainable_parameters.json)。

## 独立结果

评估门为 IoU≥0.5 且中心误差≤`max(8 px, 标注框对角线×20%)`。

| 候选 | 验证集 | run10 正例几何 | 红/紫/蓝 | run10 中位中心误差 | run10 负例框误报 |
|---|---:|---:|---:|---:|---:|
| mm40，清洗旧训练集 | 0/16（run8） | 1/30 | 0/10、0/10、1/10 | 48.15 px | 0/12 |
| mm41，加入 run8 | 4/17（run9，无负例） | **3/30** | **2/10、1/10、0/10** | **34.14 px** | **0/12** |

mm41 run10 正例按目标最大边分组：小于 40 px 为 0/14，40–79 px 为 1/10，至少 80 px 为 2/6；按画面区域为 left 0/12、center 1/5、right 2/13。改善主要来自红色和较大目标，蓝色小目标仍完全失败。完整逐例输出和评分在 [`mm40 test scored`](evidence/mm40/eval_test_scored.json)、[`mm41 test scored`](evidence/mm41/eval_test_scored.json)，汇总在 [`mm40 test summary`](evidence/mm40/eval_test_summary.json) 和 [`mm41 test summary`](evidence/mm41/eval_test_summary.json)。

最后用 run9 验证集估计每种颜色的中心偏差和尺寸比例，再把校准固定应用到 run10，结果从 3/30 降到 2/30，紫色由 1/10 降到 0/10；校准不采用。原始校准证据在 [`calibrated.json`](evidence/mm41/calibrated.json)。

## 判断与回滚

这两轮适配器都不部署、不覆盖比赛模型。若需要清理服务器实验目录，可以执行：

```bash
rm -rf /root/gpufree-data/mm40_spatial_clean /root/gpufree-data/mm41_run8_mix
```

比赛系统没有被修改，所以正式版本无需运行时回滚；若有人手动接入适配器，恢复接入前保存的 `mission_once.py` 和模型路径即可。当前证据足以否定“只靠清洗旧标签并继续训练就能得到可部署定位器”，但不能否定更大规模、整局隔离且第二人复核的数据重建在赛后继续取得进展。

路线 B 没有另建三维引擎。3.9 的真实图像平移/连续帧证据已经回答了基础的“是否能把图像内容映射到坐标”问题；本轮真实盲测把剩余问题定位在空间变化泛化、目标尺寸和颜色分布，而不是缺少三维渲染器。
