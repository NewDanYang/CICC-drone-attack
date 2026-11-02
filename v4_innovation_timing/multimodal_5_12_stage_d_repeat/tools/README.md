# 阶段 D 工具

`multimodal_5_7_stage_d_collect.sh` 是本轮 9+9 的固定顺序采集器；它按候选→基线配对，每行启动新仿真环境，调用 `multimodal_5_7_stage_d_trial.sh`，并只在正式飞行结束、解除武装后发一次 `obj gc`。不要在矩阵中途替换候选或修改 VisualServo。

`multimodal_5_7_stage_d_analyze.py` 读取服务器 `/home/ubuntu/tcei_baseline_tools/results/stage_d_20261101_retry`，按固定车道坐标生成 `analysis/metrics.tsv/json`。`prepare_switch_package.py` 和 `patch_p12e_manifest_runtime.py` 只用于复现当时的部署元数据修补，不能代替带 md5 校验的正式切换脚本。

本目录中的脚本不包含服务器口令；运行服务器工具前按仓库 `AGENTS.md` 设置 `TCEI_*` 环境变量。
