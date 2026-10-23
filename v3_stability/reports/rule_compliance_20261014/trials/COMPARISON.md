# 规则合规试部署的正式试验对照

正式目录：服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/20261014T231142_red_A0/`。本仓库保存该目录的 `scene_snapshots.jsonl`、`judgement.json`、`mission_once.out`、`observer.out`、`scene_runner.out` 和筛选出的 `aruco_and_safety_events.jsonl`；完整原始遥测为同目录 `20261014T231147_50ca06_red_telemetry.jsonl`。前一版对照为本报告存档的 [`formal_regression_summary_20261013.csv`](baseline/formal_regression_summary_20261013.csv) 与 [`aruco_window_summary_20261012.csv`](baseline/aruco_window_summary_20261012.csv) 中对应的 9 局。

两份对照 CSV 原路径为历史分支 `v3_stability/hit_balloon_v2/evidence/`，此处只复制原字节以保证本 PR 的验证证据独立可读。

| 指标 | 2026-10-13 对照（9 局） | 2026-10-14 候选（红 1 局） | 判读 |
|---|---:|---:|---|
| 指定色 Actor 删除代理判据 | 红/紫/蓝各 3/3；仅每色 1 局面对完整三球 | 3→2，删 `BP_Balloon_C_2147481420`；新 UE PID 5253 未校色，判读 `unknown` | 不计红球成功 |
| `boundary_violation_count` | 0–4；7/9 局记录恢复 | 0，未触发恢复 | 本局未观察到边界问题 |
| ArUco ENABLED→DISABLED | 0.106–0.217 s，中位数 0.139 s | **0.561 s** | 高于对照最大值 2.59 倍，触发回滚判据 |
| ArUco 回调 / 解码失败 | 1–2 / 0 | 3 / 0，速率样本 2.3/s | 识别成功，未见回调停摆；处理窗口仍变长 |
| 其他阶段 | 起飞、穿框、ArUco、逆穿、降落均成功；`mission_success` 2/9 | 同四阶段和降落成功；击球 observer 未观察，`mission_success=false` | 不能说六阶段全成功 |
| 降落 | 9/9 success | 1/1 success | 无本局降落回归 |
| 总用时 | 115.527–145.325 s，中位数 140.557 s | 137.411 s | 仍在对照范围 |

红局结束后观察 125 s，Actor 名单维持 2 个；同场景没有颜色标注，不能把唯一删除直接认定为红球。截图采集器每 2 s 对窗口做一次 XWD/PNG 取证，可能增加负载，故 **0.561 s 是观测到的候选运行时变慢，不足以单独归因于窗口代码**。任务要求一旦窗口时长明显大于对照就回滚，因此在安全落地并释放正式锁后回滚，未继续紫、蓝两局。三色“不退化”结论未取得。
