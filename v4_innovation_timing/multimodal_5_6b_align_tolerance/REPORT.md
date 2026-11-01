# FM9G VisualServo 容差验证（5.6b）

日期：2026-11-01（Asia/Shanghai）

## 当前状态

本任务未能进入服务器试验阶段。按 `AGENTS.md` 使用 `v3_stability/tools/srvctl.py` 检查 `120.209.70.195:30316`，两轮连接均在 6 次重试后返回 `Unable to connect to port 30316`。因此没有执行远程命令，没有清锁、没有修改服务器源码、没有编译、没有起飞，也没有把离线回放当作实飞结论。连接证据见 [`evidence/server_access.txt`](evidence/server_access.txt)。阶段 D 保持暂停。

本任务开始前最近一次封存记录中的冻结版本为：

- `visual_servo.cpp`: `e440050ecfc06657d5ac4b472411fef6`
- `visual_servo.h`: `d3324b0458b2160102f9bbf44546d035`

本地封存快照和 MD5 见 [`evidence/frozen_snapshot_md5.txt`](evidence/frozen_snapshot_md5.txt)。本任务没有改动这两份文件。

## 容差试验

交接要求的两次实飞均尚未执行：

| 尝试 | 预期改动 | 编译 | 实飞 | `[VisualServo]: Aligned!` |
|---|---|---|---|---|
| 1 | `deadzone_yaw=20.0`、`deadzone_vz=20.0` | 未执行 | 未执行 | 无结果 |
| 2 | 仅第一次未收敛时使用 `30.0/30.0` | 未执行 | 未执行 | 无结果 |

第一次尝试的定点差分已在本地做静态核对，只有两个 InputPort 默认值变化，见 [`evidence/deadzone_20_dryrun.diff`](evidence/deadzone_20_dryrun.diff)。这不是编译或行为证据，不能替代服务器上的备份、`catkin_make --pkg mission_pkg`、二进制 MD5 核对和红色台架局。

因此容差结论不是“20 px 收敛”“30 px 收敛”或“两次均未收敛”中的任何一个；真实结果待服务器恢复后再按交接流程取得。

## 红紫近距离丢失规则回测

在不改代码的前提下，回放了本地封存对照中的红紫日志：

- `v3_stability/reports/hit_balloon_part1_1.1/evidence/batch*/r*_{red,purple}_a1/rosout_events.jsonl`
- `v3_stability/reports/hit_balloon_part1_1.3/evidence/batch1/r*_{red,purple}_a1/rosout_events.jsonl`
- 对应的 `judgement.json`、`scene_snapshots.jsonl` 和真实帧目录保留在原始证据目录。

脚本和逐局结果：

- [`tools_rule_backtest_summary.py`](tools_rule_backtest_summary.py)
- [`evidence/rule_backtest_summary.csv`](evidence/rule_backtest_summary.csv)
- [`evidence/rule_backtest.json`](evidence/rule_backtest.json)
- [`evidence/rule_backtest_summary.md`](evidence/rule_backtest_summary.md)

提议扩展规则为：

```text
max_area_ratio >= 0.30
last_ratio >= 0.50 * 0.08 = 0.04
lost_seconds <= data_timeout + 0.25 = 1.25 s
```

回放发现至少一个需要阻止部署的风险窗口：

- `hit_balloon_part1_1.3 / batch1 / r3_purple_a1`
- 首次满足面积条件的丢失窗口：`2026-10-15T17:54:46.395+00:00`
- 最近的 VisualServo 面积日志：`35.5%`，因此 `max_area_ratio` 和 `last_ratio` 都达到建议门槛
- 没有 `SPRINT_START`
- 目标 Actor 的下一次场景快照直到 `2026-10-15T17:55:59.114+00:00` 才消失，期间没有记录到重新追踪

旧日志没有把 `last_valid_detection_time_` 或 `lost_seconds` 直接打印出来；`Target lost` 只说明已经跨过 `data_timeout=1.0 s`。这使得该窗口不能证明目标已被击破，却足以说明按现有证据不能排除“近距离遮挡/短暂丢失后提前返回成功”的风险。另有两个高面积终止窗口：`batch2/r1_purple_a1` 的 `38.7%` 和 `batch2/r1_red_a1` 的 `31.6%`；它们同样没有后续追踪恢复，相关 Actor 删除证据也只给出了最终场景状态，不能用于证明规则在丢失瞬间安全。

规则任务结论：**回测发现误触发风险，未部署红紫扩展**。服务器不可达期间没有改 `visual_servo.cpp`、没有备份/编译、没有启动节点。阶段 D 不应加载一个未经过实际编译与实飞确认的红紫规则。

## 后续解锁条件

服务器恢复后，应从冻结版本重新开始：先检查 `/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock` 和 `/tmp/px4_lock-*`，记录源码与二进制 MD5；只改 `20/20`，编译并跑一局红色台架；只有第一次没有 `Aligned!` 才回滚并进行第二次 `30/30` 紫色台架。无论结果如何，结束时都要恢复冻结源码和二进制，再由人类决定是否重新冻结某个容差值。当前没有进入阶段 D。

### 补充历史验收局

另外抽查了 1.6 的红紫历史证据包。三个紫色局在无 `SPRINT_START` 的情况下达到高面积后丢失：`B_v3/r1` 为 `61.9%`，丢失时间 `18:34:20.155`，Actor 快照在 `18:35:18.899` 才显示目标消失；`purple_forward/r1` 为 `65.8%`，丢失 `14:36:13.699`，Actor 消失 `14:37:41.614`；`purple_forward/r2` 为 `54.9%`，丢失 `14:43:07.442`，Actor 消失 `14:43:48.405`。这些窗口的延迟分别约 `58.7 s`、`87.9 s`、`41.0 s`，均足以说明“面积达到门槛后立即把丢失当成完成”缺少独立时刻证据。逐局索引见 [`evidence/historical_extra_qualifying_windows.csv`](evidence/historical_extra_qualifying_windows.csv)，原始包仍在 `v3_stability/reports/hit_balloon_part1_1.6/`。
