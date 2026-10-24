# 发布包装记录

本目录来自 2026-10-24 已完成的本地核对交付。为适配仓库审阅，做了以下可追溯调整；这些调整不构成新的实验，也未改写历史测量值、样本数、源文件哈希、基线提交或原始执行时间。

1. `results.json` 的 `provenance.repository` 从原机器的绝对工作目录改为 `.`，并添加 `repository_path_basis` 说明它表示仓库根目录。结果、运行摘要及源码清单中的仓库相对路径统一为 `/` 分隔符。
2. `source_comparison.txt` 的来源标签去掉本机工作目录前缀。展开的封存源码标签改为 `v3_stability/reports/hit_balloon_part1_final/source/final_deployment.tar.gz::成员路径`。所有标签相对于仓库根目录；原行号、摘录及 SHA256 不变。
3. 未重复提交 `evidence/frozen_source/`。其七文件及清单可从仓库已有的 [final_deployment.tar.gz](../../v3_stability/reports/hit_balloon_part1_final/source/final_deployment.tar.gz) 解出；`results.json` 中七文件的校验结果仍指向这些归档成员。
4. `run_local_audit.py` 的输出路径格式与上述约定同步：用 `.` 表示被审计仓库根目录，用 POSIX 分隔符保存仓库相对路径。统计方法、测试调用、采样数据、候选排序和评分函数未改动。
5. 核对报告的交付说明改为引用仓库已有封存包；“未推送”限定为原始本地核对阶段。新增 README 解释复跑、证据边界和手工审阅资料。
6. 发布目录中的文本文件统一为 UTF-8、LF，避免 Windows Git 换行转换造成无关差异。除上述路径与说明调整外，仅把 CRLF 换行转为 LF；保留证据中的原始行内空白、数值和文本。源文件的 MD5/SHA256 记录不因报告包装而重算。

历史记录中的 `/home/ubuntu/...` 是原服务器证据路径，作为实验来源标识原样保留，不是本地可打开路径，也不表示本次连接过服务器。含这些字段的历史 CSV、JSON 和源码摘录保持原有语义。没有为缺失的原始 ArUco 图像或服务器遥测生成替代数据。
