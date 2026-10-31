# 固定九格候选：18 局回归证据

结论以 [3.3 REPORT](../../REPORT.md) 为准；开发和三色演示在另一份 3.2 证据目录，不混入本分母。

## 文件索引

- `final_summary.json` / `.csv`：从单局原件离线重新计算的 18 行和组别统计。`confirmed_hits` 字段仅指**指定色 Actor 删除代理**，不是官方裁判分数。未知留在分母。总用时不含模型冷加载和自然语言生成。
- `trials/*.tar.gz`：原顺序 01–18，每组每色 3 局。包含部署/二进制收据、原生 CSV/遥测、模型日志/源 PNG/实际区域 PNG、窗口、采集事件、飞后 GC/对象列表/存活球颜色映射。`regression_receipts.json` 给包字节数与 SHA256，`archive_verification.json` 给包内逐文件校验结果。
- `regression_global_evidence.tar.gz`：原 plan、恢复前 plan、完整 progress、18 次切换/构建/运行/映射日志、最终回滚日志、恢复脚本和实际执行的编排脚本。含 `native_18_runs.csv`，只收本轮 18 行；另保留指定色删除正例的观察器全部已存 RGB JPEG。包内 `MANIFEST.json` 对每个成员给字节数和 SHA256；外层校验见 `global_receipt.json` / `global_verification.json`。
- `final_state.json`：整批自动回滚后的独立只读核对。源码保护 MD5、磁盘/正在运行的 BT 二进制一致性、插件/模块清理、PX4 解除武装、无正式锁和实际规划速度均有原始值。
- `sealed_visual_servo.cpp`：本轮服务器实际封存源的原始字节副本，MD5 `a63b57fa127a23cd8bb8e647f078ff21`。仓库更早的其他同名快照不能代替它解释当前蓝色重试/结束分支。只作审计，未改部署源码。
- `review/`：真实截图、原字节帧副本及派生浏览拼图，含局部框/停止后窗口反例和删除正例的人工核对。非盲标视觉准确率，也不把“非黑窗口”作为命中。
- `credential_scan.json`：提交前凭据扫描的计数与结果，不含凭据本身。
- `interim_summary.json` / `.csv`：恢复后前 14 局的历史统计快照，不是最终分母；最终采用判断只读 final_summary。

## 相机数据的准确范围

相机原话题约 10 Hz；观察器在击球段按最小 0.085 s 间隔尝试保存 JPEG，其他时段最小 0.95 s。实际保存频率受到达与调度影响，可从 header_stamp/seq 复算，不能称传感器零丢帧录像。服务器保留观察器全部已存 JPEG；Git 的单局包每十张保留一张。单局 `MANIFEST.json` 对全部已存文件记录 SHA256 和 included 标志，未入包原件仍可从 `server_session` 路径按哈希取回。全部模型源 PNG、分割区域实际输入 PNG、窗口和日志均入包。

均匀视图、确认裁剪及颜色追问并非每个 processor 项各有一张 PNG；从源图、裁剪坐标/批次索引和像素哈希无损重建。图像项、独立相机帧数、模型决策数与控制步数不可互换。

## 不连服务器、不加载模型的复算

从仓库根目录执行：

```bash
python v4_innovation_timing/multimodal_3_2/tools/verify_session_archive_v2.py v4_innovation_timing/multimodal_3_3/evidence/v2/trials
python v4_innovation_timing/multimodal_3_2/tools/analyze_archived_regression_v2.py v4_innovation_timing/multimodal_3_3/evidence/v2/trials --require-complete --output /tmp/mm_recomputed.json
python v4_innovation_timing/multimodal_3_2/tools/audit_frozen_sources_v2.py
```

分析器校验原顺序/每组每色 3 局、组别与入口/BT MD5、插件存在性、实际 0.35 m/s 参数；从原始窗口复算非黑截图和决策消费数，再检查同实例对象列表、飞行→飞后 GC→存活映射的时间顺序。伺服耗时从原始日志重算，**SPRINT_END 后可能重试，不能直接当作结束；BLUE_NEAR_CONTACT_LOSS_COMPLETE 也不是物理命中**。

早期单局包内可能保留当时的 `phase_metrics.json` 快照。最终分析器始终从事件日志和原始 planning_runs.csv 重新计算，不采用旧快照；相同日志的 Windows UTF-8 读取及蓝色结束分支统计修订没有改变飞行候选。

服务器原始根目录：`/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026`。正式试验完整目录、run_id 与时间均列于 final_summary；没有跨实例套用 Actor ID，没有把飞后真值写入识别/控制路径。
