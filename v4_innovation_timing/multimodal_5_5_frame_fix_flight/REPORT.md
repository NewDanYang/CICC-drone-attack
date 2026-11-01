# FM9G4B-V 5.5：帧一致性修复、五次矩阵与阶段 C 尝试

日期：2026-11-01（北京时间）。本轮先合入服务器已验证的 10 行帧一致性修复，再补跑完整 5 次矩阵，最后尝试一次红色阶段 C 台架。没有修改 VisualServo、安全边界、launch 速度、航点或方向参数。

## A. 修复与部署

修复前候选 runtime md5 为 `d1fde2bfa8da630393d5009c0e55f49f`；从服务器直接取得的修复版 md5 为 `5026dcf152790e962b11ebee577fb792`。二者逐行比较只增加 inference loop 中的 10 行：跟踪扫描优先查找 `model_track['seq']` 对应帧，找不到时退回 acquire，避免用最新图像套旧框。

逐行差异保存在 [`runtime_frame_fix.diff`](evidence/runtime_frame_fix.diff)，原始修复版源码保存在 [`v2/runtime.py`](v2/runtime.py)。

部署前备份：

```text
/home/ubuntu/multimodal_v2/p12e_backup_20261031/frame_fix_pre_runtime_20261101/
```

备份前两个 runtime 均为 `d1fde2bfa8da630393d5009c0e55f49f`；修复后两个实际加载路径均为 `5026dcf152790e962b11ebee577fb792`。Python 改动不需要重新 `catkin_make`，mission、bt_ros、插件和二进制 md5 未变。服务器静态验证通过：`geometry_test=passed`、`track_interpolation_test=passed`、runtime forbidden-token scan clean。

回滚：

```bash
cp /home/ubuntu/multimodal_v2/p12e_backup_20261031/frame_fix_pre_runtime_20261101/p12e_stage_b_runtime.py \
   /home/ubuntu/multimodal_v2/p12e_stage_b/v2/runtime.py
cp /home/ubuntu/multimodal_v2/p12e_backup_20261031/frame_fix_pre_runtime_20261101/model_runtime.py \
   /home/ubuntu/model/fm9g_perception/runtime.py
```

实际备份目录名为 `p12e_backup_20261031`。

## B. 修复版完整矩阵

使用真实 `PerceptionBridge` 对原始录制帧回放，核心矩阵为 45 次：1 个固定顺序轮次和 4 个打乱顺序轮次，每轮 9 个局；另有 `13_r3_red_baseline ×5` 与 `12_r2_blue_baseline ×5` 两个同局控制组，共 55 次。全部组返回 `rc=0`，脚本级崩溃为 0，审计中的 `inference_error` 为 0。

`01_r1_red_baseline` 在其 VisualServo 时间窗内没有红球真值，5 次均为 `null`，保留在原始数据中但不纳入红色定位准确率分母。其他 9 个有目标局的每局 5 次极差如下：

| 局 | 5 次 centre_pct | 极差（百分点） | ≤15 |
|---|---|---:|---|
| 04 紫 | 40.4, 44.7, 44.7, 48.9, 46.8 | 8.5 | 通过 |
| 05 蓝 | 75.0, 81.2, 76.6, 78.1, 75.0 | 6.2 | 通过 |
| 08 红 | 87.1, 83.9, 83.9, 83.9, 82.3 | 4.8 | 通过 |
| 09 紫 | 70.6, 69.0, 71.4, 69.8, 73.8 | 4.8 | 通过 |
| 12 蓝 | 59.3, 59.3, 59.3, 59.3, 59.3 | 0.0 | 通过 |
| 13 红 | 87.2, 87.2, 87.2, 87.2, 87.2 | 0.0 | 通过 |
| 16 紫 | 65.2, 71.0, 72.5, 72.5, 68.1 | 7.3 | 通过 |
| 17 蓝 | 78.8, 76.9, 76.9, 78.8, 78.8 | 1.9 | 通过 |

按颜色门槛：

| 颜色 | 有效样本 | 中位数 | 最差 | 中位数门槛 | 最差门槛 |
|---|---:|---:|---:|---:|---|
| 红 | 10 | 87.15 | 82.3 | 68 | 通过 |
| 紫 | 15 | 69.0 | 40.4 | 51 | 通过 |
| 蓝 | 15 | 76.6 | 59.3 | 62 | 通过 |

新增的同局控制组结果为：

- `13_r3_red_baseline ×5`：`85.1, 85.1, 85.1, 87.2, 87.2`；极差 2.1 个百分点。
- `12_r2_blue_baseline ×5`：`59.3, 59.3, 59.3, 59.3, 59.3`；极差 0 个百分点。

因此 B 阶段的三色中位数、最差值和每局极差门槛全部通过。逐次原始 JSON 在 [`evidence/rounds`](evidence/rounds)，汇总在 [`variance_summary.json`](evidence/variance_summary.json)，逐行表在 [`all_trial_rows.csv`](evidence/all_trial_rows.csv)。55 份完整审计 JSONL 保留在服务器 `/home/ubuntu/multimodal_v2/frame_consistent_20261101/results/fix5_20261101/audits/`，文件清单见 [`raw_audits_manifest.txt`](evidence/raw_audits_manifest.txt)。

## C. MAVROS 修复与红色台架

前两次环境启动在 MAVROS 连接处失败。复核 PX4 日志后发现真正原因是陈旧的 `/tmp/px4_lock-1`：PX4 报 `failed to create lock file: /tmp/px4_lock-1, Permission denied`，因此没有正常提供心跳，MAVROS 一直无法 `connected=true`。确认没有 PX4 进程后清理该临时锁，第三次启动成功出现 `MAVROS connected` 和 `environment_started=1`。启动日志在 [`sim_start_mavros_fix.log`](evidence/stage_c/sim_start_mavros_fix.log)。

随后执行一次红色正式台架：`20261101T121946_red_A0`。实现链路检查结果：

- processor 图片契约通过：审计记录 `images_per_item=[1]`；
- FM9G 模型调用 135 次，无 `inference_error`；
- 产生 50 张窗口截图，其中 [`window_00001037.jpg`](evidence/stage_c/window_00001037.jpg) 明确看到红球和绿色 FM9G 框；
- VisualServo 消费像素：telemetry 中 27 条 `MULTIMODAL_PIXEL`，7 条 `ALIGN/APPROACH` 相关日志；
- 模型调用时延：中位数 **0.2666 s**，P90 **0.2808 s**，最大 **0.5903 s**，命令生成同时运行；
- 没有模型进程退出或实现异常。

该单局最终 `mission_success=false`、`failure_stage=hit_balloon`，但这次单局只用于台架链路验收，不能作为成功率统计；它证明 MAVROS 和九格→像素→VisualServo 链路已经跑通，未发现“0 张图、无像素消费、模型进程退出”等实现缺陷。完整审计和正式试验证据见 [`stage_c`](evidence/stage_c)，摘要见 [`stage_c_summary.json`](evidence/stage_c/stage_c_summary.json)。

## 结论

修复版已经通过任务 B 的全部 55 次离线矩阵门槛，帧一致性修复保留。清理陈旧 PX4 锁后，阶段 C 的环境和实现链路检查均完成；红色单局命中阶段失败，但没有发现实现缺陷。当前结论为 **B 通过，C 台架链路通过，可以进入阶段 D 的多局回归；单局命中结果不作为成功率结论**。

已知未处理项保持不变：04 紫色局准确率稳定偏低；遮挡或快速平移后仍可能有短暂错误物体框。这些不是本轮新增缺陷。
