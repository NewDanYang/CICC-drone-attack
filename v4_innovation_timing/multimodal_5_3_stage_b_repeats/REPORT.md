# FM9G4B-V 阶段 B 方差复试报告

日期：2026-11-01（北京时间）。本轮只回放已有 `multimodal_v2_regression_20261026` 录制帧，没有启动仿真、没有起飞、没有修改比赛部署状态，也没有把 YOLO/HSV/真值接入运行链路。

## 实验设计

任务 A 在隔离副本的 `v2/presence.py` 中给每次 `presence_model_call` 增加了 `torch.cuda.Event` 的 `gpu_ms`、`torch.cuda.memory_allocated()` 和原有壁钟 `latency_s`。模型调用、返回值、状态机和提示词保持不变。隔离副本位于服务器 `/home/ubuntu/multimodal_v2/stage_b_repeats_20261101`，没有覆盖阶段 B 候选部署目录。

任务 B 使用真实 `PerceptionBridge` 和原始 YOLO 真值评分脚本，模型只加载一份，每轮一个新 Python 进程；运行时仍只使用 FM9G4B-V，不读 YOLO、HSV、颜色阈值、UE 真值或 `/objects`。核心矩阵为 45 次：1 个固定顺序轮次和 4 个局顺序打乱轮次，每轮包含红、紫、蓝各 3 个局。另加两个控制组：`01_r1_red_baseline` 连续 5 次、`13_r3_red_baseline` 连续 5 次。共 **55 次**，脚本级崩溃 0 次，审计中的 `inference_error` 总数 0。

每次运行的完整结果 JSON 在 `evidence/rounds/`，包含 `centre_pct`、`precision_pct`、`false_publish_absent`、完整 `event_counts`、每类模型调用数、每次壁钟延迟、每次 GPU 延迟和显存数组。55 份原始审计 JSONL 保留在服务器路径 `/home/ubuntu/multimodal_v2/stage_b_repeats_20261101/results/audits/`，清单和大小见 [`raw_audits_manifest.txt`](evidence/raw_audits_manifest.txt)。

便于逐行复核的 55 行结果表见 [`all_trial_rows.csv`](evidence/all_trial_rows.csv)。

## 45 次核心结果

中心准确率的全部数值如下；`null` 表示该录制局在规定 VisualServo 时间窗内没有对应颜色的 YOLO 真值，不能当作 0 分纳入中位数，但必须保留。

| 颜色 | 15 次原始值（3 局 × 5 次） | 有效 n | 中位数 | 最差 | 中位数门槛 | 最差门槛 |
|---|---|---:|---:|---:|---:|---:|
| 红 | `[null,83.9,87.2,29.8,null,80.6,68.1,83.9,null,69.4,null,25.5,85.1,null,82.3]` | 10 | 81.45 | 25.5 | 68 | **失败** |
| 紫 | `[42.6,60.3,52.2,53.6,42.6,70.6,57.1,38.3,56.5,40.4,80.2,55.1,38.3,63.8,61.9]` | 15 | 55.1 | 38.3 | 51 | 通过 |
| 蓝 | `[75.0,22.2,84.6,81.2,63.0,78.8,76.9,73.4,63.0,63.0,84.6,79.7,78.8,63.0,78.1]` | 15 | 76.9 | 22.2 | 62 | **失败** |

按局列出全部值：

- `01_r1_red_baseline`：`[null,null,null,null,null]`。该局时间窗没有红球真值，不能用于红色定位准确率判断。
- `08_r2_red_baseline`：`[83.9,80.6,83.9,69.4,82.3]`。
- `13_r3_red_baseline`：`[87.2,29.8,68.1,25.5,85.1]`。
- `04_r1_purple_baseline`：`[42.6,42.6,38.3,40.4,38.3]`。
- `09_r2_purple_baseline`：`[60.3,70.6,57.1,80.2,61.9]`。
- `16_r3_purple_baseline`：`[52.2,53.6,56.5,55.1,63.8]`。
- `05_r1_blue_baseline`：`[75.0,81.2,73.4,79.7,78.1]`。
- `12_r2_blue_baseline`：`[22.2,63.0,63.0,63.0,63.0]`。
- `17_r3_blue_baseline`：`[84.6,78.8,76.9,84.6,78.8]`。

有真值的同局红色控制组 `13_r3_red_baseline ×5` 为：

`centre_pct = [68.1, 68.1, 29.8, 68.1, 85.1]`，`precision_pct = [84.2, 84.2, 38.9, 84.2, 97.6]`，每次 `false_publish_absent = 0/57`。同一局、同一录制帧、同一代码在一个新进程中仍从 29.8% 跳到 85.1%，所以方差不是局间数据差异造成的。

## 顺序混杂因素

固定顺序与四个打乱顺序的配对结果见 [`variance_tables.md`](evidence/variance_tables.md)。部分局对顺序敏感：

- `13_r3_red_baseline`：固定顺序 87.2%，打乱后 `[29.8,68.1,25.5,85.1]`。
- `12_r2_blue_baseline`：固定顺序 22.2%，四次打乱均为 63.0%。
- `09_r2_purple_baseline`：固定顺序 60.3%，打乱后 `[70.6,57.1,80.2,61.9]`。

但同局红色连续控制组在顺序完全不变时仍为 `[68.1,68.1,29.8,68.1,85.1]`。因此“局在第几个位置”可能是一个影响因素，却不能解释全部方差；同一进程内的模型结果/轨迹路径仍会随机分叉。

## GPU 方差分析

45 次核心运行的每次调用 GPU 中位耗时范围：

- `acquire_tiles`：207.194–211.320 ms；
- `acquire_sweep`：450.480–463.995 ms；
- `track_sweep`：392.720–398.906 ms。

显存审计值在同一阶段内稳定为约 9.7427 GB。3 个低于 30% 的核心运行及其 GPU 中位数为：

| 局 | centre_pct | acquire_tiles | acquire_sweep | track_sweep |
|---|---:|---:|---:|---:|
| `12_r2_blue_baseline` | 22.2 | 210.070 ms | 454.759 ms | 393.761 ms |
| `13_r3_red_baseline` | 29.8 | 208.954 ms | 452.732 ms | 394.336 ms |
| `13_r3_red_baseline` | 25.5 | 210.093 ms | 463.995 ms | 396.288 ms |

低准确率没有对应统一的 GPU 延迟异常：一个低点的 `acquire_sweep` 为 463.995 ms，但另两个低点分别为 454.759 ms 和 452.732 ms；同局控制组中 29.8% 那次的 `track_sweep` 中位数 394.385 ms，也落在正常范围内。现有证据不支持“某次 GPU 被挤占导致整局失能”作为主要解释，也没有发现显存泄漏或显存阶跃。

更符合实测的倾向是**疑似数值不确定性与路径敏感性**：模型输出只需在一个边界样本上发生小变化，就会让 CSRT 从不同框开始追踪，随后状态机轨迹分叉。这个判断是倾向性结论，不是已经证明的底层 CUDA 非确定性。

## 判断

结论选择：**方差太大，需要先做推理确定性改动后再进入阶段 C**。

理由是红色和蓝色都违反“最差一次 ≥30%”：红色有效样本最差 25.5%，蓝色最差 22.2%；同一红色录制局的连续 5 次也出现 29.8% 与 85.1% 的跳变。紫色虽然中位数和最差值通过门槛，但不能抵消另外两色的失能风险。

下一步应先单独验证推理确定性（例如固定 CUDA/torch deterministic 设置，或比较 bf16 与更高精度推理），每次只改一个因素，再复跑同一矩阵。当前不应先改“连续阴性才失效”等状态机策略，否则无法判断收益来自降低状态机敏感性还是模型输出本身变稳定。

## 复现与原始证据

```bash
cd /home/ubuntu/multimodal_v2/stage_b_repeats_20261101
bash tools/run_variance_matrix.sh \
  /home/ubuntu/multimodal_v2/stage_b_repeats_20261101 \
  /home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026 \
  /home/ubuntu/multimodal_v2/stage_b_repeats_20261101/results
```

汇总 JSON 为 [`variance_summary.json`](evidence/variance_summary.json)，完整表格为 [`variance_tables.md`](evidence/variance_tables.md)，六组原始结果在 [`evidence/rounds`](evidence/rounds)。本轮没有启动仿真或飞行，也没有写入比赛部署目录。
