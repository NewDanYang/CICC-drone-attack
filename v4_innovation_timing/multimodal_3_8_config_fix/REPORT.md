# 3.8 LoRA 配置硬伤审计与 20 样本过拟合自检报告

最终复核：2026-10-29（北京时间）。本轮只使用真实 run10/run3/run7 帧、真实模型权重和服务器训练日志，没有进入实飞，也没有修改比赛飞行逻辑、VisualServo、方向 A/B 或速度参数。

## 结论

3.7 的训练配置确实存在两个硬伤：旧正则只给 MLA 注意力的 `o_proj` 挂了 LoRA，同时 `tune_vision=true` 让视觉编码器、`resampler` 和整个 `embed_tokens` 通过 `modules_to_save` 参与训练。旧记录的可训练参数为 649,374,704，其中只有 124 个 LoRA 参数张量，另有 463 个非 LoRA 张量。

本轮把目标模块改为实际存在的五类 MLA 投影，冻结视觉侧并强制移除 `modules_to_save`，只留下 84,439,040 个 LoRA 可训练参数（620 个 LoRA 张量，非 LoRA 可训练参数为 0）。这能让 20 样本自检的 loss 明显下降，说明训练梯度和标签掩码不是完全失效；但是严格几何自检最好的结果只有 15/20=75%，没有达到“训练集自身接近 100%”的硬性前置条件。因此按照止损规则，本轮停止，不跑完整 3.7 数据集、不做两级放大、不做连续帧跟踪，也不进入实飞。

配置修复值得保留为后续训练审计基线，但当前证据不足以支持九格气球定位候选。

## 第一步：模型与 tokenizer 审计

审计脚本为 [`audit_model_config.py`](tools/audit_model_config.py)，原始结果为 [`model_config_audit.json`](evidence/model_config_audit.json)。实际加载路径是 `/home/ubuntu/model/FM9G4B-V`，使用服务器既有离线环境；模型架构为 `FM9GV`。

tokenizer 中确实存在原生定位 token：

| token | 是否存在 | id |
|---|---:|---:|
| `<box>` / `</box>` | 是 | 105 / 106 |
| `<ref>` / `</ref>` | 是 | 103 / 104 |
| `<point>` / `</point>` | 是 | 109 / 110 |
| `<quad>` / `</quad>` | 是 | 107 / 108 |
| `<bbox>` / `</bbox>` | 否 | — |

示例 token 数为：`<box>123 456 789 900</box>` 18 个，JSON `{"bbox":[123,456,789,900]}` 19 个，方括号格式 20 个。坐标数字会被拆成单个数字 token；原生标签本身是词表中的单 token。模型共 62 层 self-attention，每层实际命名为：

```text
q_a_proj
q_b_proj
kv_a_proj_with_mqa
kv_b_proj
o_proj
```

3.7 使用的正则是 `llm\\..*layers\\.\\d+\\.self_attn\\.(q_proj|k_proj|v_proj|o_proj)`，在真实模型上只匹配 `o_proj`。这不是推测，旧 LoRA 参数清单中实际只有每层 `o_proj.lora_A/B`。

## 原生 `<box>` 零样本对照

使用 [`evaluate_native_box.py`](tools/evaluate_native_box.py) 在 3.7 的独立 run10 测试集上直接零样本推理，结果原件在 [`eval_native_test/`](eval_native_test/)：

| 指标 | 原生 `<box>` 零样本 |
|---|---:|
| 正例几何通过 | 2/30=6.7% |
| 红 / 紫 / 蓝 | 2/10 / 0/10 / 0/10 |
| 负例框误报 | 12/12 |
| 正例中心误差中位数 | 40.31 px |

这与 3.7 JSON 坐标-only 的 2/30、蓝色 0/10 没有明显改善，且负例误报更差。因此没有把格式差异本身当作修复证据；2a 仍使用原生 `<box>`，目的是直接利用已经存在的定位 token，同时单独审计配置修复。

## 第二步：修正后的配置

修正训练入口为 [`train_fixed.py`](tools/train_fixed.py)。它仍调用官方 `FM9G4B-V/finetune` 数据预处理、模型 forward 和 Trainer，只在构造 PEFT 后做配置审计：

- `lora_target_modules`：`llm\\..*layers\\.\\d+\\.self_attn\\.(q_a_proj|q_b_proj|kv_a_proj_with_mqa|kv_b_proj|o_proj)`；
- `tune_vision=false`，冻结 `vpm`；
- 拦截官方 `LoraConfig` 的 `modules_to_save`，强制设为 `None`；
- 再次检查所有 `requires_grad=true` 参数，若存在非 LoRA 参数立即失败；
- `r=64`、`alpha=64`、`dropout=0.05` 保持不变；
- 学习率三组分别为 `1e-4`、`5e-5`、`1e-5`，warmup 比例 5%，权重衰减 0；
- 全部使用 BF16、CPU optimizer offload、官方数据管线；为避免磁盘被 DeepSpeed optimizer checkpoint 填满，2a 对比组使用 `save_strategy=no`，每组结束保存最终适配器和 trainer state。

对照参数来自 [`prior_3_7_trainable_parameters.json`](evidence/prior_3_7_trainable_parameters.json)；修正后参数审计分别在 `lr_1e-4/trainable_parameters.json`、`lr_5e-5/trainable_parameters.json` 和 `lr_1e-5/trainable_parameters.json`。

## 2a：20 样本过拟合自检

自检数据由 [`build_selfcheck20.py`](tools/build_selfcheck20.py) 从 3.7 清洗后的训练集选择，保留 20 个不同源图像：红 7、紫 7、蓝 6，全部为正例，训练和评估使用同一组 20 张图。第一版选择曾意外重复同一源帧的多颜色任务，已保留在 `evidence/initial_selfcheck20_duplicate_frames/` 作为审计记录；正式结果使用去重后的集合，收据为 [`selfcheck20/receipt.json`](selfcheck20/receipt.json)。

三组均使用原生 `<box>x1 y1 x2 y2</box>` 答案，评估沿用 IoU≥0.5 且中心误差≤`max(8 px,标注框对角线×20%)`。

| 学习率 | 最低/末次 eval loss | 全程平均 train loss | 有效框 | 几何通过 | 中心误差中位数 |
|---:|---:|---:|---:|---:|---:|
| 1e-4 | 0.0422 / 0.0422 | 0.4093 | 20/20 | **15/20=75%** | 0.79 px |
| 5e-5 | 0.0779 / 0.0779 | 0.4990 | 20/20 | **11/20=55%** | 8.67 px |
| 1e-5 | 0.1289 / 0.1878 | 0.5646 | 19/20 | **6/20=30%** | 12.09 px |

1e-4 和 5e-5 的单步 loss 日志可以降到接近 0，说明 LoRA 参数确实收到梯度；但全程平均 train loss 仍分别为 0.4093 和 0.4990，且同一训练集的严格几何通过没有接近 100%。1e-5 还出现 1 个无法生成有效框的样本。三组的逐例评分原件分别为：

- [`lr_1e-4/eval_selfcheck/`](lr_1e-4/eval_selfcheck/)
- [`lr_5e-5/eval_selfcheck/`](lr_5e-5/eval_selfcheck/)
- [`lr_1e-5/eval_selfcheck/`](lr_1e-5/eval_selfcheck/)

最佳 1e-4 的 5 个失败例中，红 1、紫 3、蓝 1；失败以 IoU 或中心误差超门为主，没有 JSON/`<box>` 解析错误。5e-5 的失败集中在紫色和小蓝球；1e-5 既有定位偏差，也有 1 个空/非法目标输出。训练日志、GPU 内存、trainer state 和逐步 loss 全部保存在各学习率目录。

## 止损决定

2a 的目的不是比较哪个学习率“看起来更好”，而是验证流水线能否把 20 张自己见过的图稳定答对。最佳配置 1e-4 只有 15/20，低于接近 100% 的前置标准；因此不能把问题归因于“只是完整数据集还没训练够”，也不能在未通过自检时继续做 2c、两级裁剪或跟踪回放。

本轮确认了配置硬伤，但修复配置尚未让模型在训练样本上达到坐标回归的能力下限。剩余瓶颈至少仍可能来自小目标坐标监督、官方数据预处理/生成目标的对齐方式，或模型本身的精确坐标回归能力。按本任务预算和止损规则，正式放弃本加分项，不进入完整重训和实飞。

## 回滚与服务器状态

本轮没有覆盖任何比赛运行文件。若需清理服务器上的本轮离线项目，可执行：

```bash
rm -rf /root/gpufree-data/mm38_config_fix
```

训练和评估结束后已确认没有 `train_fixed.py`、`evaluate_native_box.py`、ROS 正式试验或 GPU 计算进程；3.8 适配器没有接入推理链路。
