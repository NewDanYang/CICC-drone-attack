# 速度参数、代码变更与三色气球测试总结（2026-10-30）

本报告与 `docs/speed-audit-code/` 代码包配套，记录速度审计、可复现恢复工具、代码差异和三轮现场测试。仓库代码不会自动部署到服务器；服务器源码、构建产物和运行参数仍需现场核对。

## 1. 基准与部署边界

- 仓库：`NewDanYang/CICC-drone-attack`
- 审计基准：`6499977d076a940b07e4466543f2ed1cbd306a3e`
- 服务器测试工作区：`/home/ubuntu/cicc_v1_stage_20261005/`
- 只读审计包：`baseline_tools/cicc-speed-audit-ou1hqt4f.tar.gz`
- 审计包 SHA256：`f31ebc3e0f6bc097b8a409410ae001e96572ca5756db8889c4a20e9b97a08380`

本次没有重新编译、部署源码、重启 ROS 或替换运行中的二进制。

## 2. 数值配置

### 2.1 Ego-Planner 规划限速

| 参数 | 值 |
| --- | ---: |
| `/ego_planner_node/manager/max_vel` | `0.30 m/s` |
| `/ego_planner_node/optimization/max_vel` | `0.30 m/s` |
| `/ego_planner_node/bspline/limit_vel` | `0.30 m/s` |

### 2.2 VisualServo 速度

| 参数 | 值 | 作用 |
| --- | ---: | --- |
| `/visual_servo/forward_velocity` | `1.00 m/s` | 接近速度 |
| `/visual_servo/sprint_velocity` | `1.50 m/s` | 冲刺速度 |
| `/visual_servo/sprint_time` | `1.20 s` | 冲刺持续时间 |

这些是控制目标或轨迹约束，不等于每一时刻无人机实际速度。正式测试通过 V2.1 JSONL 遥测记录实际 `speed`。

## 3. 代码交付内容

`docs/speed-audit-code/` 包含：

- `restore_official_speed.py`：只读预检、带备份的速度恢复、回滚和哈希校验工具；默认只检查，不写文件。
- `approved_fingerprints.json`：允许仅发生已审计速度差异的源文件指纹。
- `run_hit_regression_formal.sh`：设置正式 LLM 回归速度（`1.0/1.5/1.2`），保存参数、源码和二进制 SHA256，并记录 ROS 证据。
- `ego-planner-max-vel.patch`：Ego-Planner `max_vel` 从实验档位恢复到 `0.30` 的差异。
- `bt_ros-sprint-speed.patch`：移除蓝球专用 `1.0` 冲刺分支，统一读取 `visual_servo/sprint_velocity`。

这些文件是交付和复现代码，不代表已经在服务器执行。原仓库中的历史实验源码仍保留，不能仅凭存在认定为运行版本。

## 4. 测试结果

### 紫球

- 目录：`results/formal_trials/20261030T005356_purple_V1/`
- 总耗时：`141.199 s`
- 行为树：`SUCCESS`
- 现场：**未命中**
- 视觉伺服约 8 秒搜索超时，最大目标面积约 `1.1%`，未进入冲刺
- 外层 `ForceSuccess` 使任务仍可能返回 `SUCCESS`

### 蓝球

- 目录：`results/formal_trials/20261030T010721_blue_V1/`
- 总耗时：`141.652 s`
- 行为树：`SUCCESS`
- 现场：**命中**
- 自动日志没有确认冲刺，启动时 `max_ratio=0.000`，约 8 秒后搜索超时

### 红球

- 目录：`results/formal_trials/20261030T014137_red_V1/`
- 总耗时：`216.383 s`
- 自动结果：`ABORTED`，失败阶段为 `cross_frame`
- 模型漏生成 `cross_frame`，实际序列为 `takeoff → detect_aruco → return_cross_frame → hit_balloon:red → land`
- 现场观察：**整体动作良好**
- 由于自动链路中止，本轮不是完整的自动验收结果

## 5. 判据与限制

1. `ForceSuccess` 会把视觉伺服失败包装成行为树成功，不能单凭 `mission_success` 或 `SUCCESS` 宣称击破。
2. observer 对 `VisualServo` / `TargetTracker` 的日志匹配不完整，实际失败可能显示为空状态。
3. 蓝球的人工命中与自动日志不一致；紫球人工未命中且日志明确搜索失败；红球人工观察良好但自动任务中止。
4. 服务器仍有 FM9G 目标选择、非目标保护、稳定等待、规划导航/返航等增强逻辑，不能声称整套代码与官方基线完全相同。

## 6. 复现建议

先用 `restore_official_speed.py` 做只读检查，再在独立备份目录中应用；应用后保存参数、源码哈希、二进制哈希和每轮遥测。不要重复启动 `AgentContestMap.py`，每次只保留一个地图进程。

