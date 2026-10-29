# 基线恢复后的完整审计复跑结果（2026-10-27）

本目录发布已完成的本地复跑报告、脚本和完整验证证据。审计对象固定为修复提交 `340a52c744b1f19fdbda0e18ef77f14a6f5400bd`，并不表示当前主分支或服务器已处于该版本。**没有执行新服务器仿真、飞行或真实模型推理。**

## 先看这些文件

| 内容 | 入口 |
|---|---|
| 本次报告与正式实验的后续计划 | [复跑报告](复跑报告.md) |
| 原始完整结果下载：31 个文件，包含展开的封存源码 | [RAW_RESULTS_20261027.zip](RAW_RESULTS_20261027.zip) |
| 各分组结果、版本、哈希和样本数 | [results.json](results.json) |
| 与 2026-10-24 审计的逐项比较 | [comparison_to_20261024.json](comparison_to_20261024.json) |
| 61 个参与审计的源码文件校验值 | [source_manifest.json](evidence/source_manifest.json) |
| 2,817 个源文件在执行前后保持不变 | [source_unchanged_check.json](evidence/source_unchanged_check.json) |
| 29 项命令回归、6 项显示回归的执行日志 | [命令回归](evidence/test_mission_once_fallback.py.log)、[显示回归](evidence/test_aruco_display_loop.py.log) |
| 标准库复跑脚本 | [run_local_audit.py](run_local_audit.py) |
| 发布文件校验清单 | [SHA256SUMS.txt](SHA256SUMS.txt) |
| 发布时做的说明调整 | [PACKAGING.md](PACKAGING.md) |

四个规划器文件均匹配历史 `original_md5`，均不匹配候选 `deployed_md5`；其他九个审计结果分区与旧报告一致。命令回归 29 PASS / 0 FAIL，显示回归 6 PASS / 0 FAIL。测试桩、历史候选回放和历史日志复算不能替代正式整机对照实验。

`evidence/frozen_source/` 保留七份封存源码及其清单；目录中的六份差异、CSV、JSON 和运行摘要均可直接浏览。这里的封存文件只用于证据核对，不是待部署的官方运行版本。

## 对应的历史提交

- [基线恢复 PR #13](https://github.com/NewDanYang/CICC-drone-attack/pull/13)：恢复四文件、保留方向 A 补丁载荷并说明官方快照的权威性边界。
- [本次实际审计的提交](https://github.com/NewDanYang/CICC-drone-attack/tree/340a52c744b1f19fdbda0e18ef77f14a6f5400bd)。
- [上一轮文档核对 PR #8](https://github.com/NewDanYang/CICC-drone-attack/pull/8)：原核对报告、创新文档修订稿与旧审计结果。

上述链接用于定位证据；PR 的当前合并状态以 GitHub 页面为准。

## 复现

使用 Python 3.12 或更新版本，仅依赖标准库。先将本目录的 `run_local_audit.py` 复制到仓库外。然后在含有上述修复提交的 Git 仓库中导出固定快照，明确关闭自动换行转换：

```text
git -c core.autocrlf=false archive --format=zip --output=../repaired-source.zip 340a52c744b1f19fdbda0e18ef77f14a6f5400bd
python -m zipfile -e ../repaired-source.zip ../repaired-source
python -B ../run_local_audit.py --repo ../repaired-source --out ../new-audit-results --zip ../repaired-source.zip
```

使用新的外部目录，核对两个子测试的退出码及 PASS/FAIL 数，不仅看主脚本退出码。脚本生成分组结果、日志和统计；中文报告、前后比较、源文件未改动检查是本次额外整理的资料，不由该脚本单独生成。2,817 文件检查只覆盖当时导出的快照，不包括后来加入的本目录。

此次上传只增加报告和证据。需要撤销发布时回退对应文档提交即可；没有服务器部署需要回滚。
