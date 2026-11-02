# v7_servo_closed_loop

FM9G 多模态大模型接入击球闭环的第三轮（v5 → v6 → v7）。
**当前状态：v7.0 已部署并实飞 13 局；观察器 2 局 success，但取证为"计时器成功"，物理命中仍为 0/11。**

先读 [REPORT.md](REPORT.md)。

| 目录 | 内容 |
|---|---|
| `code/` | 服务器上实际运行的 8 个 Python 模块快照（v7.0 candidate） |
| `tools/` | 离线分析：审计统计、HSV 真值、真值对账、静止拟合、定位阶梯探针、环境起停 |
| `patches/` | 部署脚本（与 v6 相同，未改动） |
| `evidence/` | 试验汇总 CSV、第 12 局关键帧 |

部署/回滚命令见 REPORT.md §5。
