# 用时优化候选离线准备报告

日期：2026-10-21  
当前状态：**仅完成本地离线分析和可回滚补丁准备，未部署、未重启服务器、未跑新正式局。**

用户反馈仿真服务器当前已满，因此本轮先停在离线阶段。服务器恢复且确认没有其他人占用后，
再按候选 1 → 候选 2 → 候选 3 的顺序逐项实测。当前正式部署状态不变，没有触碰
`v3_stability/hit_balloon_v2/` 及其他已封存气球代码。

## 1. 证据边界

- 历史计时基线：[`timing_baseline.md`](../timing_baseline.md)。其中 24 局的起飞均值为
  16.0 s（中位数 17.9 s，范围 12.6–18.9 s），第一次穿框均值 15.9 s。
- 本报告的候选结果不是“修复有效”的结论。没有当前服务器的 3 色 × 3 局实测，就不能
  推断可靠性或最终用时收益。
- 击球阶段不在本任务的改动范围内；任何气球命中结论继续沿用 Part 1 的封存报告，不能
  用本报告的离线结果包装成整体成功。
- 历史握手延迟的可复核摘要见
  [`evidence_offline/handshake_latency_summary.md`](evidence_offline/handshake_latency_summary.md)。

## 2. 候选 1：起飞 OFFBOARD/ARM 固定重试间隔

### 离线方法

目标是只把 `drone_action_node.h` 中两个默认参数从 5.0 s 改为 1.5 s：

```cpp
throttledSetMode(..., interval_sec = 1.5);
throttledArm(..., interval_sec = 1.5);
```

本地官方输入文件 MD5：

```text
official_baseline/catkin_ws/src/mission_pkg/include/base/drone_action_node.h
7334b435faceae983f46f3dd185da172
```

用历史真实 JSONL 配对得到的确认延迟（n=11）：

| 事件 | 均值 | 中位数 | P95 | 最大 |
|---|---:|---:|---:|---:|
| OFFBOARD | 0.434 s | 0.350 s | 0.957 s | 0.993 s |
| ARM | 0.406 s | 0.339 s | 0.879 s | 0.975 s |

历史数据支持“5 s 退避明显长于确认延迟”这一假设，但它不是当前服务器的实时测量。
因此候选 1 的离线结论为：**有空间，暂不采用**。只有当前实时 P95 在目标间隔下仍留出
安全余量，且红、紫、蓝各至少 3 局都没有起飞失败，才能采用。

### 本地补丁验证

`patches/patch_candidate1_throttle.py` 在临时副本上完成：

1. MD5 门禁通过；
2. 只替换两个声明，应用后 MD5 为 `c415ddd8243afcc64c181be45bdac5e3`；
3. 读取到两个 `1.5` 声明；
4. 按 manifest 回滚后恢复 `7334b435faceae983f46f3dd185da172`。

补丁脚本自身 MD5：`ceb181672cb50f97c720ec9cd7bb5e13`。

### 服务器恢复后的实测门槛

先用只读观察器记录每次请求到 `/mavros/state` 确认的延迟，不能以历史数据代替。若当前
分布仍远小于 5 s，再应用 1.5 s 候选，分别跑红、紫、蓝各 ≥3 局，记录：起飞耗时、起飞
是否成功、失败阶段、总耗时。任一颜色出现新的起飞失败，立即回滚并判定不采用。

## 3. 候选 2：`WaitForStablePosition` 事件等待

### 离线静态检查

旧候选的设计是用“位置误差 ≤0.15 m、速度 ≤0.08 m/s，连续确认 0.50 s，最多 2.00 s”
替换穿框观察点的固定 2 s `Delay`。节点只读里程计，不发布新的飞行指令；超时仍返回
成功，保持原固定等待的失败语义。

候选 payload 来自：

- `v2_time_optimization/working_source/src/mission_pkg/include/nodes/action/wait_for_stable_position.h`
  - MD5 `c90e547a9fe65331bf49c23753c26abd`
- `v2_time_optimization/working_source/src/mission_pkg/src/nodes/action/wait_for_stable_position.cpp`
  - MD5 `ef785b83fdf04d176e78c41f3c060cdc`

在本地官方副本上，`patch_candidate2_wait_stable.py` 完成了应用和回滚检查：

- `bt_ros.cpp` 输入 MD5 `f3883b30c69f3bdc248d50ac9fc0ad9e`，应用后
  `4c23ef9a943f38868ac878e2c06b04f8`；
- `llm_mission.launch` 输入 MD5 `7ebdb609e86fcf664bf58f6d2e587ea3`，应用后
  `37723e4ddfaef24f16ba3fcfefafbb72`；
- XML 中四个 `optimization/*` 参数和 `WaitForStablePosition` 节点文本均出现；
- 回滚后两个输入文件恢复原 MD5，新增节点文件被删除。

补丁脚本 MD5：`54bd17249aeb3207d593cafe71044f95`。脚本已加上全量预检：只有两个源文件
的锚点、payload 和目标文件状态全部通过后，才创建备份并写入，避免过期源码留下半套
修改。

### 现有历史试验为何不能作为今天的结论

`v2_time_optimization/experiments/formal_v2_patch1_red/` 的 2026-10-01 两次红色试跑
不能作为当前稳定基线上的公平验证：一次在 `checkArrival` 无进展 20 s 后卡住，另一次
在 ArUco 20 s 超时后失败；两次都早于后续死锁修复和 ArUco CLAHE 修复。历史文件仍保留
为反例证据，但不能据此宣称候选 2 快或可靠。

候选 2 的离线结论：**补丁结构可回滚，但性能和可靠性未验证，不采用。** 服务器恢复后
必须先核对当前 `bt_ros.cpp` 的 MD5/锚点，确认没有已经存在的 `WaitForStablePosition`，
再移植、`catkin_make --pkg mission_pkg`，并在当前稳定基线上红、紫、蓝各 ≥3 局。每局
要同时记录穿框等待时间、后续 ArUco、整体失败阶段和总耗时。

## 4. 候选 3：Ego-Planner `max_vel` A2

### 离线静态检查

候选档位为 A0=0.30、A1=0.35、A2=0.40、A3=0.45、A4=0.50 m/s。按任务要求先只准备
A2；A0 与 A2 launch 的差异只有一行 `max_vel`，其余规划参数不变。A0 本地输入 MD5：

```text
v2_1_ego_velocity/configs/A0/FS-J310_ego-planner.launch
e6806d41207404427860e0f90713d14d
```

临时副本应用 A2 后 MD5 为 `eced1e92648e01153f2a1b15618f9582`，回滚恢复 A0 MD5。
补丁脚本 MD5：`c8d2008e70dd813634ee7468a9b1d71f`。

配置说明确认这个 launch 参数会传给：

```text
/ego_planner_node/manager/max_vel
/ego_planner_node/optimization/max_vel
/ego_planner_node/bspline/limit_vel
```

离线结论：**A2 的改动边界清晰，但没有任何当前基线的速度收益或可靠性证据，暂不采用。**

服务器恢复后先部署 A2，启动后必须用 `rosparam get` 核对以上三个参数都等于 0.40，再跑
红、紫、蓝各 ≥3 局；只有穿框/逆穿框时间改善且没有新失败，才考虑 A1/A3。A2 失败则停止
该方向，不继续提高速度档位。

## 5. 当前决定与后续顺序

| 候选 | 离线结果 | 当前决定 | 当前是否改变正式部署 |
|---|---|---|---|
| 1：重试间隔 5.0→1.5 s | 历史握手延迟支持有空间；缺当前实时测量 | 等服务器后先测 | 否 |
| 2：事件稳定等待 | 静态补丁可应用/回滚；旧试跑被环境和旧 ArUco 混淆 | 等当前源码核对后再测 | 否 |
| 3：A2 `max_vel=0.40` | 仅一行配置差异；未测用时/可靠性 | 候选 1、2 结束后再测 | 否 |

每个候选完成后都先回滚到当时最佳已验证状态，再开始下一个；不合并候选，除非三项独立
结果都支持且额外合并确认不超过半天。若任一候选的 3 色数据不能同时证明用时收益和
可靠性不下降，结论就是不采用。没有服务器数据前，不创建“最终部署状态”或整体成功率
结论。

## 6. 补丁、备份和回滚命令

三个脚本都要求 MD5 门禁，并在目标文件旁写入 `.bak_time_opt_candidate*` 备份和 manifest。
服务器端实际路径以当次检查结果为准；下面是回滚形式：

```bash
# 候选 1
python3 patch_candidate1_throttle.py \
  --source /home/ubuntu/catkin_ws/src/mission_pkg/include/base/drone_action_node.h \
  --manifest /home/ubuntu/tcei_baseline_tools/time_optimization/candidate1_manifest.json \
  --rollback

# 候选 2
python3 patch_candidate2_wait_stable.py \
  --bt /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp \
  --launch /home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch \
  --node-header /home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/action/wait_for_stable_position.h \
  --node-source /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/wait_for_stable_position.cpp \
  --header-payload <payload.h> --source-payload <payload.cpp> \
  --manifest /home/ubuntu/tcei_baseline_tools/time_optimization/candidate2_manifest.json \
  --rollback

# 候选 3
python3 patch_candidate3_max_vel.py \
  --source /home/ubuntu/catkin_ws/src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch \
  --manifest /home/ubuntu/tcei_baseline_tools/time_optimization/candidate3_manifest.json \
  --expected-md5 <部署前现场读取的 A0 MD5> --rollback
```

候选 2 回滚前还要确认新增 `.cpp/.h` 没有被其他改动覆盖；脚本发现 MD5 不匹配会拒绝
回滚，避免覆盖他人工作。

## 7. 服务器恢复后的前置检查

按 `AGENTS.md` 先确认 `/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`
及最近 10 分钟的 `baseline_runs.csv` 没有他人活动；当前服务器爆满，本轮没有执行这些
操作，也没有建立锁、重启节点或上传补丁。

## 8. 文件完整性摘要

| 文件 | MD5 |
|---|---|
| `patches/patch_candidate1_throttle.py` | `ceb181672cb50f97c720ec9cd7bb5e13` |
| `patches/patch_candidate2_wait_stable.py` | `54bd17249aeb3207d593cafe71044f95` |
| `patches/patch_candidate3_max_vel.py` | `c8d2008e70dd813634ee7468a9b1d71f` |
| 官方起飞头文件输入 | `7334b435faceae983f46f3dd185da172` |
| 官方 `bt_ros.cpp` 离线输入 | `f3883b30c69f3bdc248d50ac9fc0ad9e` |
| 官方 `llm_mission.launch` 离线输入 | `7ebdb609e86fcf664bf58f6d2e587ea3` |
| A0 Ego-Planner launch 输入 | `e6806d41207404427860e0f90713d14d` |

本报告和三个补丁是离线准备产物；在完成服务器实测前，不能把它们当成已部署修复。
