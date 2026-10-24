# 2026-10-24 文档与源码核对及离线验证

本目录保留对提交 `f0d795516e44af903de7c22403ee93c430e70c71` 的本地核对结果。**没有运行新服务器仿真、飞行、真实模型推理或现场图像采集。** 历史实验数据的重新统计与测试桩回归不能代替新的整机性能对照。

先读 [核对报告](核对报告.md)；可供负责人审阅的文字在 [创新文档修订稿](创新文档修订稿.md)。主要发现是官方基线目录含团队规划器修改、安全恢复基线身份混淆、返航距离指标误名，以及蓝球丢失时间窗描述偏差。

| 内容 | 入口 |
|---|---|
| 分组结果、版本和哈希 | [results.json](results.json) |
| 标准库离线复跑脚本 | [run_local_audit.py](run_local_audit.py) |
| 参与计算的 61 个仓库文件的字节数、MD5、SHA256 | [source_manifest.json](evidence/source_manifest.json) |
| 有行号及哈希的源码摘录 | [source_comparison.txt](evidence/source_comparison.txt) |
| 29 项命令逻辑断言、6 项显示逻辑断言的原输出 | [命令日志](evidence/test_mission_once_fallback.py.log)、[显示日志](evidence/test_aruco_display_loop.py.log) |
| 历史记录复算 | `evidence/` 中的 CSV、JSON、摘要及六份源码差异 |
| 发布时的路径与包装调整 | [NORMALIZATION.md](NORMALIZATION.md) |

七文件封存源码及原清单已经存于仓库的 [final_deployment.tar.gz](../../v3_stability/reports/hit_balloon_part1_final/source/final_deployment.tar.gz)，本目录不重复提交展开副本。源码摘录中的 `归档路径::成员路径` 指向这个归档内的原始字节；差异文件的 `frozen_20261019/` 是同一归档的比较标签。复跑时脚本会把归档展开至外部结果目录的 `evidence/frozen_source/`。

## 复跑

需要 Python 3.12 或更新版本，仅依赖标准库。为复现本次数字，请使用上述提交的完整仓库快照，并保留原始数据；后续分支的修改或 Git 换行转换可能改变哈希。脚本会执行快照内已有的两个测试脚本、耗时统计脚本和规划统计脚本，并以测试桩加载命令选择器；不调用模型加载函数。

在仓库根目录执行以下命令，`../cicc-local-audit-rerun` 必须是仓库外的新目录：

```text
python -B v4_innovation_timing/local_audit_20261024/run_local_audit.py --repo . --out ../cicc-local-audit-rerun
```

可选添加 `--zip /path/to/CICC-drone-attack-main.zip`，记录下载包校验值及 ZIP 注释中的提交 ID；没有 ZIP 时不产生这些字段。脚本拒绝把输出写入仓库或其子目录。终端会打印运行摘要，`results.json` 保留各回归子进程的退出码及 PASS/FAIL 数；核对时应同时检查这些字段，不能只依赖主脚本退出码。

脚本生成机器可读结果、六份差异、两份回归日志、历史统计及解出的封存副本。两份中文报告、`source_comparison.txt`、`source_unchanged_check.json` 是本次额外整理的审阅资料，不由脚本自动生成；`run_summary.txt` 是原执行的终端摘要。`source_unchanged_check.json` 仅描述原始下载快照 2,808 个文件的 SHA256 检查，不声称新增本目录后的仓库仍与 ZIP 完全相同。

原始执行环境、时间戳、数值及源文件哈希保留在结果中；发布只做 [已记录的包装调整](NORMALIZATION.md)。本目录未改动运行代码、参数、历史原始数据或创新草稿。需要撤销本次提交时可通过 Git 回退对应提交；没有服务器部署需要回滚。
