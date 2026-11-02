# FM9G 阶段 D 扩大样本重复记录

本目录记录 `docs/astra-handoff-fm9g-stage-d-repeat.md` 要求的第二轮 9+9 实测。该轮没有修改候选 runtime、tracking 插件、VisualServo、速度、航点或安全边界；仍使用 5.7 阶段 D 的切换和飞后 Actor 快照协议。颜色判定使用已修正的车道映射：`x=5.6 → blue`，`y=+2.1 → purple`，`y=-2.1 → red`。红紫互换修正来自上一轮真实摄像头帧核验，不能再使用旧的 `y=+2.1 → red` 映射。

## 执行记录

- 18 局全部完成：候选 9 局、基线 9 局；每色 3 局，顺序为 red → purple → blue，候选先跑、基线后跑。
- 每局均单独重启 UE/ROS；飞前 `before_count=3`，飞行结束后才执行一次 `obj gc`，再采集 `after/late15/late45/late90/settled` 和最终存活演员位置。
- 18 局 `gc_rc=0`，每局都有对象快照、位置查询、observer、原始 rosout SHA256 和正式 trial 目录。
- 运行器返回码和 `mission_success` 只作为状态字段；命中字段来自修正后的 Actor 删除车道判定。
- 候选指纹与 5.7 阶段 D 相同：runtime `5026dcf152790e962b11ebee577fb792`，mission `de03cd1a5687f7bc0664ea52f3cd095f`，bt_ros 源码 `9a1e8d2a5913968b1c2300cad1dc02f7`，二进制 `1f1592dc8d33613bf4b772a4eb2f6dfb`。基线为 mission `fca24bf1142ca8cddfb9e8d39c387a43`、bt_ros `9b1cefe9dfa431418435f7f8f63a60ed`、二进制 `abb5c49eb21b1b333d88677def4921ab`。

## 逐局数据

`hit/removed` 是指定颜色命中数/删除演员数；`first_align_s` 是从该局 observer `start_time` 到首次 `Aligned!` 的秒数；`search_s` 是 `Position-held search` 日志按时间戳累计的秒数；候选 `model_n/med/p90` 来自对应候选 audit 的 `presence_model_call.latency_s`。

| 轮 | 色 | 条件 | Actor 判定 | 命中/删除 | APPROACH 次数 | first_align_s | search_s | 总用时(s) | 边界 | model_n | med(s) | p90(s) |
|---:|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| 1 | red | candidate | hit | 1/1 | 0 | — | 50.478 | 132.255 | 否 | 139 | 0.267029 | 0.281749 |
| 1 | red | baseline | hit | 1/1 | 1 | 80.735 | 9.029 | 93.547 | 否 | — | — | — |
| 1 | purple | candidate | hit | 1/1 | 13 | 102.047 | 43.163 | 157.737 | 是 | 130 | 0.269548 | 0.507350 |
| 1 | purple | baseline | hit | 1/1 | 7 | 99.902 | 28.099 | 140.690 | 否 | — | — | — |
| 1 | blue | candidate | hit | 1/1 | 8 | 74.037 | 42.036 | 136.139 | 是 | 136 | 0.262304 | 0.503782 |
| 1 | blue | baseline | hit | 1/1 | 0 | — | 50.352 | 205.373 | 否 | — | — | — |
| 2 | red | candidate | hit | 1/1 | 6 | 82.565 | 44.156 | 129.137 | 否 | 133 | 0.271696 | 0.282644 |
| 2 | red | baseline | hit | 1/1 | 0 | — | 48.188 | 128.122 | 否 | — | — | — |
| 2 | purple | candidate | hit | 1/1 | 11 | 82.852 | 44.170 | 143.368 | 是 | 129 | 0.268206 | 0.491685 |
| 2 | purple | baseline | hit | 1/1 | 7 | 101.217 | 29.700 | 133.007 | 否 | — | — | — |
| 2 | blue | candidate | wrong_lane | 0/1 | 1 | 118.120 | 41.098 | 136.036 | 否 | 119 | 0.268376 | 0.528641 |
| 2 | blue | baseline | hit | 1/1 | 2 | 72.841 | 2.008 | 92.464 | 否 | — | — | — |
| 3 | red | candidate | hit | 1/1 | 0 | — | 50.220 | 168.531 | 否 | 148 | 0.264047 | 0.276994 |
| 3 | red | baseline | hit | 1/1 | 0 | — | 43.193 | 135.138 | 否 | — | — | — |
| 3 | purple | candidate | no_deletion | 0/0 | 4 | 125.048 | 20.093 | 140.105 | 否 | 94 | 0.277658 | 0.518875 |
| 3 | purple | baseline | hit | 1/1 | 10 | 89.001 | 18.060 | 135.154 | 否 | — | — | — |
| 3 | blue | candidate | hit | 1/1 | 0 | — | 48.204 | 165.661 | 否 | 135 | 0.263777 | 0.518659 |
| 3 | blue | baseline | hit | 1/1 | 6 | 77.468 | 37.931 | 145.214 | 否 | — | — | — |

完整机器表在 [evidence/metrics.tsv](evidence/metrics.tsv)，Actor 代理摘要在 [evidence/actor_verdicts.tsv](evidence/actor_verdicts.tsv)。

## 汇总数字（仅记录，不作接入判断）

- 候选：`7/9`；红 `3/3`，紫 `2/3`，蓝 `2/3`。
- 基线：`9/9`；红 `3/3`，紫 `3/3`，蓝 `3/3`。
- 候选的两类非 hit 行为：紫色第三轮 `no_deletion` 1 局，蓝色第二轮 `wrong_lane` 1 局；本轮没有 `extra_deletion`。
- 总用时中位数：候选 `140.105 s`，基线 `135.138 s`。
- 边界事件：候选 3/9，基线 0/9。
- 候选从未进入 `APPROACH`：3/9；没有达到交接文档规定的 `≥6/9` 中止条件。
- 候选 9/9 都有 `MULTIMODAL_PIXEL` 和完整 audit 链，候选审计最后事件均为 `closed`。

## 证据、部署和回滚

- `session_p*` 目录保存每局的五次对象快照、最终位置、状态、post-GC 输出和 SHA256；`evidence/formal_raw/` 保存 observer、mission_once、planning、runner、judgement 和对象原始文件。
- [evidence/deployment_manifest.json](evidence/deployment_manifest.json) 保存候选、基线和最终状态指纹；最终状态为基线，复核文件为 [evidence/final_baseline_status.json](evidence/final_baseline_status.json)。
- [evidence/sha256_all.tsv](evidence/sha256_all.tsv) 汇总 18 局原始哈希。
- 服务器矩阵输出根目录：`/home/ubuntu/tcei_baseline_tools/results/stage_d_20261102_repeat`。完整 rosout 日志仍保留在各局 `trial_dir`，路径见 `evidence/metrics.tsv`。
