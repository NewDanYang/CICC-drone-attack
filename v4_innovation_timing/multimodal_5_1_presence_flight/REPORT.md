# FM9G4B-V presence-sweep 阶段 B 接入报告

日期：2026-10-31（北京时间）。本报告承接 P12e 的阶段 A 通过结果，记录同进程 runtime 接入、MD5 备份、编译和不起飞离线验收。

## 阶段 A 依据

P12e 在同一组 9 个真实 VisualServo 窗口上得到 357/494（72.3%）中心正确、93.5% 发布精确率；红色 92/109、紫色 154/242、蓝色 111/143。获取延迟中位数为 1.0 s。面积比中位数 0.65、尾部最大残留 8 帧仍保留在证据中，分别对应 YOLO 框偏松和蓝色横幅误判，不能被改写成已解决。

P12e 状态机是本阶段基线：模型每周期做一次瓦片/四向存在扫描，CSRT 只在两次九格结果之间插值；一次阴性先暂停发布，第二次阴性才丢弃；精扫使用 7 档、窗口因子 2.2、模型结果保持 1.5 秒；气球框形状先验保持在高宽比 `[0.9,1.6]`。

## 接入实现

接入包位于 `v2/`：

- `presence.py` 提供 GPU FastPresence 和 P12e 的瓦片/四向扫描；只询问“有没有指定颜色气球”，不包含检测器、HSV、YOLO 或 UE 真值。
- `runtime.py` 删除了 `OverlapLocalizer`、`local_regions` 和旧语义确认路径，改用 P12e 状态机。
- 保留 session/epoch 门控、`MultimodalTargetTracker` C++ 插件、帧龄 0.35 s 输出门、窗口截图、`ReplayTracker`、ROS 审计和 `/multimodal/objects` 链路。
- 新增 pending handoff barrier，确保上一轮模型结果被 tracking worker 消费并更新后，下一轮才选择 acquire/track，避免并发覆盖。
- `scale_resolution=224` 在官方 processor 上显式固定，使 FastPresence 与部署时实际 processor 配置一致；模型仍只有一份，命令生成和图像推理共用同一 `model_lock`。

## 离线验收

静态验收通过：`validate_stage_b.py` 通过，runtime 源码中没有旧 `OverlapLocalizer`/HSV/YOLO 读取路径，P12e edge-box 单元检查通过。

FastPresence 与同配置官方 processor 在 3 个真实采集帧上比较：最大概率绝对差 **0.00356**，低于 0.03。原始结果在 [`fastpresence_parity.json`](evidence/stage_b/fastpresence_parity.json)。

真实帧桥接 smoke 使用 FM9G 模型、`PerceptionBridge`、`NativePresenceSweep`、`ReplayTracker` 和审计发布路径，未启动 ROS 飞行。最新蓝色窗口记录 103 次发布、81 个可配对框，但与 P12e 逐帧中心差中位 **12.0 px**、最大 131.36 px，未达到 ≤3 px 验收门。原始审计在 [`runtime_smoke_blue_audit_handoff_barrier.jsonl`](evidence/stage_b/runtime_smoke_blue_audit_handoff_barrier.jsonl)，评分在 [`runtime_replay_score.json`](evidence/stage_b/runtime_replay_score.json)。

这项差异没有被隐藏或当作通过。日志显示模型推理结果、pending handoff 和模型年龄门均生效；剩余差异集中在真实帧回放的 CSRT 插值/帧龄调度与离线 P12e 虚拟时钟之间。阶段 C 台架飞行因此暂不执行。

## 部署与编译

正式试验锁检查时不存在，`baseline_runs.csv` 最后一行未变化。部署前备份位于服务器：

```text
/home/ubuntu/multimodal_v2/p12e_backup_20261031
```

备份记录了原始 mission、bt_ros、二进制和安全 guard MD5。候选源码已激活并编译通过：

- mission：`de03cd1a5687f7bc0664ea52f3cd095f`
- bt_ros：`9a1e8d2a5913968b1c2300cad1dc02f7`
- plugin：`2a2e1b7fc0b2ca37291ecbef97ade06f`
- bt_ros binary：`1f1592dc8d33613bf4b772a4eb2f6dfb`

完整状态在 [`final_status.json`](evidence/stage_b/final_status.json)，编译日志在 [`build_candidate.log`](evidence/stage_b/build_candidate.log)，服务器路径和候选包 SHA 在 [`server_manifest.json`](evidence/stage_b/server_manifest.json)。

## 回滚

候选保持部署但未起飞。停止相关节点、确认没有正式试验锁后执行：

```bash
cd /home/ubuntu/multimodal_v2/p12e_stage_b
bash patches/build_p12e.sh baseline /home/ubuntu/multimodal_v2/p12e_backup_20261031
```

脚本会恢复 mission、bt_ros、原始二进制并检查 `TargetTracker` 字符串和候选插件不存在。没有修改 VisualServo、安全边界、launch 速度、航点、方向 A/B 或优化参数。

算法问题仍是 CSRT 插值与离线虚拟时钟的差异；环境问题包括录制窗口首帧间隔和真实 ROS 回调调度；本轮没有大模型命令输出异常。三类问题在审计中分开记录。
