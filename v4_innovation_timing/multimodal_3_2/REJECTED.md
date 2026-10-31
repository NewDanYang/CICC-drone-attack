# 首轮失败实现存档，不是待部署版本

本文件只针对 2026-10-23/24 首轮的 `staging/` 与 `source/`，不描述后来 `v2/` 的接入和回归结果。

本目录的 `staging/mission_once.py` 和 `source/mission_pkg/` 保留最后一局的原始测试字节，MD5 见 `evidence/candidate_manifest.json`。它们包含已确认的传图错误和未修复的时序/跟踪问题，不是一个已通过的 3.2 实现。

禁止把它整份覆盖到封存源码目录；不会因为合并本 PR 自动部署。部署脚本默认退出，只保留显式复现失败候选的入口，供后续审计。服务器已恢复原始版本。

首轮输入契约的正确写法已在 `tools/audit_image_contract.py` 中验证；当时没有据此重开飞行，也没有把未经现场验证的修正混入该测试快照。首轮结论见 `REPORT_first_attempt.md`，其 3.3 当时未启动。第二次实施与实际回归见当前 `REPORT.md` 和 `../multimodal_3_3/REPORT.md`，不能混用两轮样本或部署脚本。
