# Astra 交接：合入帧一致性修复 → 补齐矩阵 → 阶段 C 红色单局（5.4 → 5.5）

**这份交接取代 `docs/astra-handoff-fm9g-determinism.md`。** 确定性测试不用再做：方差的根因已经找到，不是数值问题。如果你已经开始跑确定性测试，停下，把已有的结果放进你的分支，标注"被 5.4 取代、未完成"即可，不需要跑完。

开始前请读：`v4_innovation_timing/multimodal_5_4_frame_consistency/REPORT.md`。

## 0. 背景（不需要你重新验证）

`v2/runtime.py` 的 `inference_loop` 在跟踪扫描时，图像用的是最新帧，窗口位置却来自跟踪线程上一次更新所在帧的框。线程滞后一帧时，窗口套错位置，框被持续拉偏，最终钉在背景上。修复只有 10 行：跟踪扫描改用 `model_track['seq']` 对应的那一帧，找不到该帧就退回重新获取。

修复后，同局重复的极差：红 13 从 61.7 降到 4.2，蓝 12 从 40.8 降到 0。三色最差值分别为 82.3 / 44.7 / 59.3（修复前红 25.5、蓝 22.2）。每局只跑了 3 次，**还没达到你 5.3 的每局 5 次标准**。

## 1. 硬约束（不变）

1. 运行链路不得出现 YOLO、HSV、颜色阈值、UE 真值、`/objects`（离线评分脚本中可以用）。
2. 不改 VisualServo、安全边界、launch 速度参数、航点、方向 A/B、用时优化。
3. 只加载一份模型，与命令生成共用 `model_lock`。
4. 部署前备份并记录 md5；回滚用脚本，并核对二进制。
5. 用服务器前检查 `/tmp/tcei_formal_trial.lock` 和 `baseline_runs.csv` 最后一行。
6. 口令只用环境变量。
7. 失败局不得剔除。所有结论都要附样本数和原始证据路径。

## 2. 任务 A：合入修复（预算 0.5 小时）

1. 用 `v4_innovation_timing/multimodal_5_4_frame_consistency/v2/runtime.py`（md5 `5026dcf152790e962b11ebee577fb792`）替换阶段 B 候选的 runtime。先对比 diff，确认相对你的 `d1fde2bf…` 版本只多出第 195–204 行这 10 行；有任何其他差异立即停止并报告。
2. 部署到 `/home/ubuntu/multimodal_v2/p12e_stage_b/v2/runtime.py` 和实际加载路径 `/home/ubuntu/model/fm9g_perception/runtime.py`，前后记录 md5，并更新 `final_status` JSON。这是 Python 改动，**不需要** `catkin_make`。
3. 跑 `validate_stage_b.py`，确认通过。

## 3. 任务 B：在修复版上补齐 5.3 矩阵（预算 1 小时）

直接使用你自己的 `run_variance_matrix.sh`，`STAGE_B` 指向修复后的目录。跑完整的 5 轮（1 个固定顺序 + 4 个打乱顺序）加两个同局控制组（13 红 ×5、12 蓝 ×5）。

判断门槛与 5.3 相同：每色中位数 ≥ 68 / 51 / 62（红 / 紫 / 蓝），最差 ≥ 30。另外**新增**一条：每局 5 次的极差 ≤ 15。

- 全部通过 → 进入任务 C。
- 任一色最差 < 30，或任一局极差 > 15 → 停止，报告是哪一局，并附该局最差那次和最好那次的发布时间线（用 `tools/diverge_timeline.py`）。不要自行修改状态机。

## 4. 任务 C：阶段 C 红色单局台架（预算 1 小时，仅在任务 B 通过后执行）

按原交接 `docs/astra-handoff-fm9g-presence-sweep.md` 第 4 节执行：启动仿真，跑红色 1 局候选，检查以下四项：

1. processor 每次调用的图片数正确；
2. 窗口截图里框住了红球；
3. VisualServo 消费了像素（`MULTIMODAL_PIXEL` 与 `ALIGN/APPROACH err` 日志对得上）；
4. 定位时延（中位数和 P90）是在命令生成同时占用 GPU 的情况下测得的。

如果出现实现缺陷（图片数为 0、没有像素消费、模型进程退出），只修实现、不改算法，最多 2 次；第 3 次仍失败就停止。跑完后记录 Actor 删除代理结果，单局结果**不作为**成功率结论。

## 5. 已知但本轮不处理的问题

- 04 紫色局准确率稳定偏低（约 45–51%）。
- 05 蓝色局横幅标志误报。

这两项在报告里列出即可，不要尝试修复。

## 6. 交付物

新目录 `v4_innovation_timing/multimodal_5_5_frame_fix_flight/`，内容包括：部署 diff 与前后 md5、任务 B 的全部原始 JSON 与分布表、任务 C 的单局证据包（若执行），以及三选一结论：

- 可以进入阶段 D；
- 任务 B 未过（附具体哪一局）；
- 任务 C 出现实现缺陷（附证据）。

提交到你自己的分支并推送。不要合并到 `main`。
