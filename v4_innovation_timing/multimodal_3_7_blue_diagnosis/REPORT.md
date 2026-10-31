# 3.7 蓝色定位诊断与坐标-only 微调报告

最终复核：2026-10-29（北京时间）。本轮严格按“先诊断、再拆分任务、独立留出、失败即止损”执行，没有进入实飞。

## 最终结论

本轮放弃九格多模态加分路线，不再开启第八轮训练。

蓝色 3.6 失败的首要根因是数据质量和目标尺度，而不是蓝色物理上不可见：37 个蓝色训练正例中人工复核发现 13 个不应作为紧致真值框使用，其中包括框在三脚架/地面的样本和把紫球标成蓝球的样本；清洗后剩余 24 个蓝色训练框的最大边全部不超过 30 px。3.6 测试的 10 个蓝色正例中还有 1 个（`run7_00023_blue`）实际是紫球。

将区域问答完全移除、只训练坐标问答后，独立新采集轮次 `run10` 的测试结果仍为：整体几何 2/30（6.7%），蓝色 0/10，红色 2/10，紫色 0/10。蓝色继续挂零，整体远低于 30% 止损线，因此任务拆分没有解决坐标回归瓶颈。

## 蓝色根因诊断

原 3.6 测试蓝色 10 例的逐例审计保存在 [`blue_diagnosis.json`](evidence/blue_diagnosis.json)，原始评分和模型输出分别在 [`blue_test_scored_36.json`](evidence/blue_test_scored_36.json) 与 [`blue_test_predictions_36.jsonl`](evidence/blue_test_predictions_36.jsonl)。结论如下：

| 现象 | 数字 | 判断 |
|---|---:|---|
| 输出非空框 | 9/10 | 模型通常不是完全拒识 |
| 空/非法框 | 1/10 | `run7_00053_blue` 输出非法 JSON 框 |
| 几何通过 | 0/10 | 不是单个异常样本造成 |
| 可解析蓝框中心误差中位数 | 19.10 px | 高于 8 px 基线门槛 |
| 蓝色目标最大边中位数 | 27 px | 目标很小，约 20% 对角线门极严 |
| 可解析框中心偏移 | 中位约右 12 px、下 10 px | 存在系统性坐标偏移 |

原图逐例检查显示，大部分蓝球是可见的高对比蓝色球体，问题主要是框的中心和尺度没有落在紧门内；`run7_00023_blue` 是明确的紫球误标，不能把它当作蓝色视觉难度证据。

训练集 37 个蓝色正例的 13 个拒绝项及原因：

- 5 个框落在三脚架/地面，蓝球在框外；
- 4 个实际是紫球；
- 4 个严重遮挡或框过松，不能作为紧致可见球体真值。

清洗后蓝色样本数为 24，最大边中位数 27 px、最大值 30 px；红色 run3 训练框最大边中位数约 78 px，紫色约 50 px。蓝色训练分布因此同时存在标签污染和尺度偏斜。

## 独立数据集

新采集事件记录：[`run8_events.jsonl`](evidence/run8_events.jsonl)、[`run9_events.jsonl`](evidence/run9_events.jsonl)、[`run10_events.jsonl`](evidence/run10_events.jsonl)。采集脚本 [`collect_real_frames_v3.py`](evidence/collect_real_frames_v3.py) 和 [`collect_real_frames_v4.py`](evidence/collect_real_frames_v4.py) 不设置 `command_speed_cap`，只发布位置 setpoint；采集前核对的官方参数为 `manager/optimization/bspline max_vel=0.35`。run10 的最终测试正例全部来自速度≤0.35 m/s 的筛选帧。

本轮集合按采集轮次完全隔离：

| 集合 | 来源轮次 | 坐标问答数 | 正例红/紫/蓝 | 负例 |
|---|---|---:|---:|---:|
| train | run3、run7（清洗蓝标） | 114 | 31 / 23 / 24 | 36 |
| validation | run8 | 28 | 10 / 4 / 2 | 12 |
| test | run10 | 42 | 10 / 10 / 10 | 12 |

训练、验证和测试没有共享采集轮次；SHA/来源收据和实际 JSON 在 [`dataset/receipt.json`](dataset/receipt.json)、[`dataset/cases.json`](dataset/cases.json) 中。run8 的蓝色验证样本只有 2 个，属于小样本监控，不承担最终结论；最终结论使用独立 run10 的 10 个蓝色正例。

## 坐标-only 训练

训练数据只生成 bbox 问答，区域问答数量为 0。LoRA 配置保持 3.6 起点：`r=64`、`alpha=64`、`dropout=0.05`，视觉侧可训练、语言侧冻结，BF16 与 CPU optimizer offload，学习率 `1e-6`，验证/保存间隔 200 步。数据构造脚本为 [`build_mm37_dataset.py`](tools/build_mm37_dataset.py)，启动脚本和实际资源审计副本在 [`finetune_coord.sh`](evidence/finetune_coord.sh) 与 [`train_budget_coord.py`](evidence/train_budget_coord.py)。

验证 loss 曲线为：

| 步数 | validation loss |
|---:|---:|
| 200 | 0.6657 |
| 400 | 0.6789 |
| 600 | 0.7095 |
| 800 | 0.7109 |
| 1000 | 0.7181 |

最佳检查点是 200 步，训练在 1000 步按早停控制结束。根目录适配器与 checkpoint-200 的 SHA-256 为 `b1f6f38db3d81ed65ff129d1c58f52a4715d923fbe447665ee2d66fab71a4926`；checkpoint-1000 为 `815103484e9e0263b2b4013ccab1994a7c7f0fea54db6005b550db2d6fbcaa68`。训练状态和资源证据见 [`trainer_state_coord.json`](evidence/trainer_state_coord.json)、[`training_memory_coord.jsonl`](evidence/training_memory_coord.jsonl)、[`gpu_memory_coord.csv`](evidence/gpu_memory_coord.csv)。

## 独立留出评估

评分沿用原几何门：IoU≥0.5 且中心误差≤`max(8 px, 标注框对角线×20%)`。坐标-only 评估器为 [`evaluate_coord.py`](tools/evaluate_coord.py)，没有重新加入区域任务。

### validation（run8）

- 整体几何：1/16=6.25%；
- 蓝色：0/2，中心误差中位数 62.35 px；
- 红色：1/10；紫色：0/4；
- 负例框误报：3/12。

### test（run10，最终独立留出）

- 整体几何：2/30=6.7%；
- 红色：2/10，紫色：0/10，蓝色：0/10；
- 蓝色中心误差中位数：44.20 px；
- 整体中心误差中位数：39.37 px；
- 负例框误报：0/12。

完整结果在 [`eval_coord_test_summary.json`](evidence/eval_coord_test_summary.json)、[`eval_coord_test_scored.json`](evidence/eval_coord_test_scored.json)、[`eval_coord_validation_summary.json`](evidence/eval_coord_validation_summary.json) 中。

相对于 3.6 混合训练的历史测试结果（3/26 几何、蓝色 0/10），本轮测试集合已换成完全独立的 run10，因此不把百分比做成严格同集合增减比较；但蓝色在独立 run10 仍为 0/10，且整体只有 2/30，已经足以触发预设止损条件。

## 决定与回滚

坐标-only 候选不部署，不进入实飞。服务器上只保留独立采集、训练和离线评估证据；没有修改比赛飞行逻辑、VisualServo、方向 A/B 或用时优化候选。若需清理训练/评估目录，可执行：

```bash
rm -rf /root/gpufree-data/mm37_coord_only
```

最终建议是正式放弃本加分项，把剩余比赛时间投入已封存的主流程稳定性和可得分阶段。继续加蓝色样本或继续拆分任务，在当前坐标回归误差和独立测试表现下没有证据支持。
