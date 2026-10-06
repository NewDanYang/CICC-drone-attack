# V2.1 experiments

正式运行时，每局使用独立配置和独立 telemetry JSONL。建议命令：

```bash
python3 /home/ubuntu/tcei_baseline_tools/run_baseline.py \
  --color red --no-launch-llm --timeout 300 \
  --v21-telemetry --v21-config A0 --v21-max-vel 0.30 \
  --v21-log-dir /home/ubuntu/tcei_baseline_tools/v2_1_ego_velocity/experiments
```

observer 仍只订阅和记录，不发布控制消息。每个速度档完成后停止，先分析再切换下一档。
