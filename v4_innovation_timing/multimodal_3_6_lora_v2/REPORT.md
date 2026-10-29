# 3.6 LoRA 数据扩充与重新微调报告

最终复核：2026-10-29（北京时间）。本报告只使用真实仿真帧、真实训练日志和离线推理结果；没有用合成图像替代证据，也没有进入实飞验收。

## 结论

本轮不采用，不能申报九格多模态加分通过。已经完成了一轮真实帧扩充和官方 LoRA 重训，但几何门没有达到要求：留出测试的 26 个正例中只有 3 个通过（11.5%），红色 2/6、紫色 1/10、蓝色 0/10；三色整体区域命中为 19/26（73.1%），但测试负例有 9/24 次区域误报、9/24 次框误报。验证集几何为 2/27。几何门、区域门和负例门均未通过，因此没有执行实飞。

当前结果还有两个会降低结论强度的审计问题：validation/test 与 train 都包含同一个 `run7` 采集轮次，虽无跨集合重复 SHA-256，却仍有相邻帧泄漏；采集脚本记录了 `command_speed_cap=0.30`，而规则要求整个仿真过程不改飞行速度参数。故本轮结果只能作为“扩充数据后仍未得到可采用候选”的失败证据，不能作为严格整局分组泛化率或规则完全合规率。

## 数据采集

服务器上的采集产物位于 `/root/gpufree-data/mm36_data/run3/` 和 `/root/gpufree-data/mm36_data/run7/`，原始事件记录已归档到 [`run3_events.jsonl`](evidence/run3_events.jsonl) 和 [`run7_events.jsonl`](evidence/run7_events.jsonl)。采集节点是 [`collect_real_frames_v2.py`](evidence/collect_real_frames_v2.py)，订阅真实 RGB 话题并保存 PNG，同时记录里程计速度和离线 `/objects` 提议；推理链路没有加入 YOLO 调用。

冻结数据包含 138 张唯一图像、228 个颜色任务行：

| 集合 | 图像数 | 正例（红/紫/蓝） | 负例行 | 采集轮次 |
|---|---:|---:|---:|---|
| train | 82 | 31 / 23 / 37 | 36 | run3、run7 |
| validation | 27 | 6 / 10 / 11 | 24 | run7 |
| test | 29 | 6 / 10 / 10 | 24 | run7 |
| 合计 | 138 | 43 / 43 / 58 | 84 | run3、run7 |

正例图像级数量已经超过三色各 40 的最低目标，但不能称为 40–50 个独立采集局：红、紫、蓝都主要来自两次采集轮次，且 run7 被拆到了三个集合。完整计数、区域分布、尺寸段、速度和 SHA 审计在 [`analysis.json`](evidence/analysis.json)；原始数据收据在 [`receipt.json`](evidence/receipt.json)。

尺寸段覆盖（按标注框最大边）：train 为小/中/大 48/23/20，validation 为 15/8/4，test 为 14/7/5；三集合都包含边缘裁切例。正例的里程计速度均不超过 0.35 m/s，train/validation/test 的最大值分别为 0.345/0.295/0.339 m/s。

采集节点的事件头同时记录 `sealed_planner_max_vel=0.35` 和 `command_speed_cap=0.30`。没有看到修改 Ego-Planner `max_vel` 的证据，但“整个仿真过程速度不能改”的新规则覆盖命令速度上限，所以本轮速度合规只能标为 REVIEW，不能写成 PASS。

## 标注质量

标注来自真实 RGB 帧。第一遍使用离线 `/objects` 提议或像素掩码辅助框，随后对球体边界做了人工修正；每个原始帧又由同一人隔开时间、盲看原始帧接触表复核一次。数据收据明确写明“same reviewer blind second pass”，没有第二位独立标注人，因此这不是独立双人复核，像素金标准也没有建立。该限制按要求如实保留。

`cases.json` 中每个样本都有源图 SHA-256；跨集合重复 SHA 为 0，但按采集轮次检查得到 `run3 → train`、`run7 → train/validation/test`。这就是本轮不能通过“整局分组”纪律的直接证据。

## 重新微调

训练沿用 3.5 已验证流程：LoRA `r=64`、`alpha=64`、`dropout=0.05`，视觉侧可训练、语言侧冻结（`tune_vision=true`、`tune_llm=false`、`use_lora=true`），BF16，CPU optimizer offload，学习率 `1e-6`，验证/保存间隔 200 步。启动参数和 DeepSpeed 配置入口保存在 [`finetune_lora.sh`](evidence/finetune_lora.sh)，LoRA 配置保存在 [`adapter_config.json`](evidence/adapter_config.json)。

验证 loss 为：200 步 0.3939、400 步 0.2774、600 步 0.2667、800 步 0.2674、1000 步 0.2526、1200 步 0.2593、1400 步 0.2619。最佳检查点是 1000 步；训练在 1400 步按耐心阈值停止，没有为了延长训练而放松早停。根目录适配器与 checkpoint-1000 的 SHA-256 均为 `0b9cf0575efed70b21eb179e3db2da688b21a37c92762b6824bada98929b3aac`，checkpoint-1400 为 `a61593459697e7e760f5c91ed476a18f13f65621b9a20adf8346a75aeec4f5f0`。训练状态原件见 [`trainer_state.json`](evidence/trainer_state.json)，GPU/训练过程记录见 [`gpu_memory.csv`](evidence/gpu_memory.csv) 和 [`training_memory.jsonl`](evidence/training_memory.jsonl)。

## 离线评估

评估使用冻结的 3.5 判据：IoU≥0.5 且中心误差≤`max(8 px, 标注框对角线×20%)`，并保留区域、几何交集和负例错误门槛。评估程序只向模型传入真实图像、颜色和任务提示，随后才把标注接回评分；输出原件是 [`eval_adapter_test_scored.json`](evidence/eval_adapter_test_scored.json)、[`eval_adapter_validation_scored.json`](evidence/eval_adapter_validation_scored.json) 及对应 summary。

在同一组 26 个测试正例上，base→LoRA 的变化为：区域 7/26→19/26，几何 0/26→3/26，中位中心误差 104.88 px→25.24 px；负例区域误报 4/24→9/24，负例框误报保持 9/24。这个对照说明视觉区域判断有改善，但坐标回归仍远离门槛，且负例行为变差。base/LoRA 的测试 summary 都在 `evidence/` 中；它们只是在同一新测试集合上的成对对照，不替代严格整局留出。

作为历史参照，3.5 的冻结留出集合是 55 个正例，几何通过 11/55=20%，中心误差中位数 18.95 px；该集合与本轮测试集合不同，不能把两组百分比当作严格的前后实验差值。

### 颜色–区域先验专项

训练集的模态区域为红=left（18/31）、紫=right（14/23）、蓝=center（19/37）。测试集中打破该模态的样本为红 6、紫 4、蓝 5。LoRA 在这 15 个样本上的区域命中为红 5/6、紫 1/4、蓝 4/5；几何交集通过为红 2/6、紫 1/4、蓝 0/5。专项结果仍然不能证明真正学到颜色视觉特征：样本数小，而且这些测试样本与训练样本共享 run7 采集轮次。

## 门槛判定与实飞决定

- 三色区域门：测试 19/26=73.1%，低于 85%，不通过；虽然相对同集合 base 提升 46.2 个百分点，但不能抵消绝对门槛失败。
- 整体交集几何门：3/26=11.5%，低于 70%，不通过。
- 分色几何门：红 2/6=33.3%（低于 70%）、紫 1/10=10%（低于 60%）、蓝 0/10=0%（低于 60%），不通过。
- 测试负例门：区域误报 9/24、框误报 9/24，均高于 1/12，不通过。
- 验证集：几何 2/27，不能支持提前采用。

因此未按“红色先行 3 局、再扩展三色各 3 局”的流程实飞；也没有改动比赛飞行逻辑、VisualServo、方向 A/B 或已采用的用时优化候选。

## 采用与回滚

本轮候选不部署，服务器上只新增了离线评估目录 `eval_adapter_validation_v2/`、`eval_adapter_test_v2/` 和 `eval_base_validation_v2/`，没有覆盖任务节点或正式比赛配置。若需要清理本轮评估目录，可执行：

```bash
rm -rf /root/gpufree-data/mm36_lora_v2/eval_adapter_validation_v2 \
       /root/gpufree-data/mm36_lora_v2/eval_adapter_test_v2 \
       /root/gpufree-data/mm36_lora_v2/eval_base_validation_v2
```

若曾把该适配器接入其他服务，回滚应恢复接入前保存的 `mission_once.py`/模型路径；本轮没有执行该接入，因此没有新的运行时回滚动作。

## 止损后的下一步

如果重新开启这一方向，下一轮必须先采集至少三次互相独立的轨迹，并按整局把 train/validation/test 分开；采集脚本删除或证明 `command_speed_cap` 不改变官方速度；标注至少采用第二人独立复核或同一人两次完全盲标并逐框给出差异统计。只有完成这三项后，才值得再花一天训练。当前证据支持的结论是：数据量增加和 LoRA 重训改善了区域识别，但在这组真实帧上没有把坐标回归推过几何门，不能进入实飞。
