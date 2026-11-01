# Astra 交接：多跑几局收集真实闭环录像（不改代码，不判断命中率）

开始前请读：`v4_innovation_timing/multimodal_5_8_box_growth/REPORT.md`。

## 0. 背景和目的

我在接近阶段框尺寸偏小这个问题上找到了真实机制（扫描曲线显示模型其实知道目标比窗口大，但代码钳制丢弃了这个信号），也试了 4 版修复，但全部在离线 9 局矩阵上是净负。我判断离线矩阵本身用的是旧 YOLO 驱动的轨迹，不能代表九格真实闭环会怎么飞，而我手头只有 3 局真实九格闭环录像，样本太小不能下结论。

**这次任务的唯一目的是收集更多真实闭环录像，不判断任何命中率、不修改任何代码、不验证任何修复方案。** 这是纯数据收集，风险极低。

## 1. 硬约束（不变）

1. **不改任何代码**。`visual_servo.cpp/.h` 保持冻结值（`a63b57fa127a23cd8bb8e647f078ff21` / `d3324b0458b2160102f9bbf44546d035`），感知 runtime 保持 5.4/5.5 修复后的版本，不做任何实验性修改。
2. 每局开始前完整重启仿真环境（`cleanup_sim.sh` 确认进程清零和锁清空，再 `start_sim_environment.sh` 等 `environment_started=1`，确认 `armed=False` 且里程计在起点附近）。
3. 用服务器前检查试验锁。
4. 口令只用环境变量。

## 2. 任务：跑 6 局，红紫蓝各 2 局

用 `run_formal_trial.sh` 正常跑，**不需要任何特殊参数或修改**：

```bash
bash ./run_formal_trial.sh red
bash ./run_formal_trial.sh purple
bash ./run_formal_trial.sh blue
bash ./run_formal_trial.sh red
bash ./run_formal_trial.sh purple
bash ./run_formal_trial.sh blue
```

每局之间都要完整重启环境。每局跑完不用做任何分析或判断，只要确认：

- `audit.jsonl` 和 `images/` 目录完整生成（在 `/home/ubuntu/tcei_baseline_tools/results/multimodal_v2/<时间戳>/` 下）；
- 原始 `formal_trials/<时间戳>_<颜色>_A0/` 目录和里面的 `logs/*.jsonl`（rosout）完整生成。

**不需要看这一局是否命中、是否对齐、是否进入 APPROACH——这些都不是本次任务要判断的事。** 只要流程正常跑完（无论成功还是超时）就算完成，失败局也要保留，不要因为"看起来没进入 APPROACH"就重跑。

## 3. 交付物

列出全部 6 局的以下信息，不需要分析：

- 服务器路径：正式试验目录 + 对应的 `multimodal_v2` 感知审计目录；
- 每局的 `observer.out` 原始内容（不需要解读，原样贴出来）；
- 6 个前后 md5 核对（确认代码确实没有改动）。

新目录 `v4_innovation_timing/multimodal_5_9_closedloop_data/`，提交到当前分支。**不用写任何结论性的报告，这次只是交数据，后续分析我来做。**
