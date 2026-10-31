# GitHub 交付说明

2026-10-31 按用户要求，将本轮研究源码、报告和实验记录提交至独立分支，并以草稿 PR 供审核。没有合并到正式分支，没有部署或重启仿真服务器。

阅读入口：[完整报告](README.md)。最新实验：[60 场景原始 CSV](evidence/validation-smooth-v6/replanning_benchmark.csv)；[结果汇总](evidence/research_summary.json)；[构建及验证清单](evidence/validation-smooth-v6/run_manifest.json)。

验收状态：任务 A 尚未完成整机恢复验证；任务 B 为经过离线自检并接入 manager 的研究候选。60 个合成场景中，原版返回 56 条轨迹，候选替换 2 条，另 54 条保留，4 次原失败保留。两条选中轨迹分别快 2.00% 和 20.86%，jerk RMS 分别下降约 6.88% 和 26.17%；全部有解场景提速中位数为 0%，均值为 0.4082%。没有新增真实飞行结果，不能将这些数字作为整机成绩。

原始记录保持不变。`evidence/provenance.json` 等文件中的 `upstream_publication: false` 指生成该份本地证据时尚未上传，不是对本次 GitHub 交付状态的描述。源码快照、运行日志内的本机路径用于追溯；复现时按 README 为 `run_checks.py` 传入实际目录。

候选默认关闭，不提高限速，不改变仿真倍率。真实地图的已知空闲标记和完整六阶段对照飞行仍需验证。不要将离线测试使用的 ROS/地图替身部署到正式环境。
