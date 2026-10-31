# 3.2 收尾：接入实现未通过，已回滚

试验：2026-10-23 至 10-24；最终复审：2026-10-25（北京时间）。

**结论：3.2 未完成验收，3.3 未启动。四次红色实现调试局均不能作为九格视觉能力或气球命中率样本。** 本轮最大问题是接入代码没有真正把图片传入模型。此前过程更新将重复 bbox 和约 7 秒耗时归因为模型/架构能力不足，该归因撤回。本报告以原始日志和模型输入契约复核后的结论为准。

## 1. 架构与实际实现

[架构决策](architecture_decision.md)比较了决策级九格加 YOLO、九格直接低频控制、九格初始 bbox 加非语义跟踪等方案。选定的最小候选是同一 `mission_once.py` 模型实例输出气球 bbox，再由光流传播到 `/multimodal/objects`，独立 C++ tracker 将其转换为封存 `VisualServo` 的 `pixel_target`。未修改 VisualServo 状态机、安全边界、方向 A/B 或用时优化参数。

候选实际实现了 ROS 门控、模型进程生命周期、输出解析、发布/消费链及窗口调用；**真实图像识别这一前提没有实现成功**。候选完整测试字节保留在 [staging/mission_once.py](staging/mission_once.py)，MD5 `9e59ada4270b086f15e6133dc854cedb`。这是已否决的历史快照，不能直接部署。

## 2. 原始证据和复算

- [原始证据包](evidence/raw_trials.tar.gz)：14,867,071 字节；SHA256 `d6280e6dfa05858af047fa1e3cc044321cbe80f3564e7c64982d63ccf933683d`。包含四局 `mission_once.out`、`observer.out`、`planning_runs.csv`、两份原始 JSONL、环境 rosout、实际模型 chat 源码摘录、相机配置和候选各版源码。`MANIFEST.json` 内 34 个文件的 SHA256/字节数已逐项复核。
- [自动复算结果](evidence/summary.json)由 [summarize_evidence.py](tools/summarize_evidence.py)生成。所有局均完整列出，不筛掉失败局。
- [离线检查记录](evidence/offline_checks.json)：schema 检查、原始 BT 补丁输出 MD5 与错误输入拒绝、命令辅助函数 AST 保持一致、shell 语法和默认禁止部署检查通过；这些均不代表飞行或视觉验收。
- 服务器原件仍在 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/<试验名>/`。环境原件为 `/tmp/tcei_sim_environment/ros_home/.ros/log/5e13867c-cef1-11f1-816f-f6531ce6a97a/rosout.log`。

```bash
python tools/summarize_evidence.py evidence/raw_trials.tar.gz --output evidence/summary.json
```

上述命令在本目录运行，只读归档、不加载模型、不发布 ROS 命令。

## 3. 四局数据

| 试验目录 | 总用时 s | 进入 tracker 后持续时间 s | 模型桥收到启动门控 | 输出决策 / pixel_target 日志 | 观测器结果 |
|---|---:|---:|---:|---:|---|
| `20261023T235740_red_A0` | 173.723 | 50.000 | 0 | 0 / 0 | `mission_success=false`，hit 状态空 |
| `20261024T001131_red_A0` | 164.943 | 约 50.000 | 0 | 0 / 0 | 同上 |
| `20261024T002937_red_A0` | 173.182 | 50.000 | 0 | 0 / 0 | 同上 |
| `20261024T004338_red_A0` | 164.086 | 50.000 | 26 | 13 / 24 | 同上 |

前三局 `mission_once.out` 都在发布命令后打印“退出”：正式脚本使用 `stdin=/dev/null`，输入循环收到 EOF，daemon 图像线程随进程退出。原先怀疑 ROS 门控连接时序，增加了启动 5 秒内每 0.2 秒重发；日志并未证明连接时序是根因。真正修复生命周期的是最后一版的 `rospy.spin()`。

另有一次**手工门控的静态调试**出现 `_publish_box(..., age=...)` 参数不匹配；后续已修正。该异常发生在正式局之前，不能当成第一局失败根因。

### 最后一局只证明数据通路

- `MULTIMODAL_WINDOW_READY` 1 条；没有保存窗口截图，无法独立验收窗口内容是否与飞行目标对齐。
- `MULTIMODAL_DECISION` 13 条，框全为 `[10,250,80,340]`；`MULTIMODAL_CONTROL` 49 条，C++ `model bbox -> pixel_target` 24 条。证明输出坐标被消费，**不能证明这些坐标来自图像识别**。
- 13 次调用耗时最小/中位/最大为 **6.899 / 7.417 / 7.794 s**；其中包含击球 tracker 停止后的调用。因图片实际未进入模型，这不是视觉推理时延，不能与 3.1 的图像调用 P50/P95 作性能对比。
- tracker/VisualServo 活跃窗口为 UTC `16:45:12.682–16:46:02.682`（北京时间 10 月 24 日 `00:45:12.682–00:46:02.682`）。唯一安全边界事件在 UTC `16:46:22.489`，即 tracker 停止后 **19.807 s**、返航 GoTo 已开始。活跃窗口内边界事件 **0**；不能写成“九格击球阶段触边”。同局发生和因果关系应分开。
- 四局 `bt_success=true`；命中外围有 `ForceSuccess/Timeout`，观测器还没有适配新 tracker 名称。`hit_balloon_status` 为空不能直接等同物理漏击。本轮没有独立 Actor/破裂帧证据，**不报告 0/4 命中率，也不声称确认击破**。

## 4. 输入契约审计：为什么图片没有传入

服务器实际 `modeling_fm9gv.py` MD5 为 `629bf42b6bd3685c7e1fae178d4fa330`。其 `chat()` 第 321–322 行只在 `content` 为字符串时自动将 `image=` 插入内容；第 334–339 行只收集内容列表中的 `PIL.Image.Image`。本轮调用是：

```python
model.chat(image=image, msgs=[{"role": "user", "content": [MULTIMODAL_PROMPT]}], ...)
```

列表只有文本，自动插图分支不会执行，最终 processor 收到 **0 张图片**。3.1 评测器使用字符串 `content=PROMPT`，没有这个错误，不能把本轮结果用于否定 3.1。

[输入契约审计脚本](tools/audit_image_contract.py)提取**实际模型 chat 方法和测试候选 kwargs 的 AST**，用 processor spy 在张量/推理前停止。[结果](evidence/image_contract_audit.json)：

| 输入形式 | processor 收到图片数 |
|---|---:|
| 本轮实际：`image=im; content=[prompt]` | **0** |
| 修正契约：`image=im; content=prompt` | **1** |
| 修正契约：`image=None; content=[im,prompt]` | **1** |

这是接口复现测试，不是合成图片性能试验；没有调用 GPU。复现命令：

```bash
python tools/audit_image_contract.py --model-source /home/ubuntu/model/FM9G4B-V/modeling_fm9gv.py
```

## 5. 其他尚未解决的实现缺陷

以下来自测试快照审查，不声称都在飞行中实际触发：

1. 默认订阅 sensor2；正式气球 RGB 配置是 **sensor1**。即使修正传图，仍须先保证与 VisualServo 使用同一摄像机几何，并验证分辨率和通道顺序。
2. bbox 框龄从推理完成时计，隐去了采集到推理完成的延迟；旧帧坐标会当成新框。光流初始化用旧帧，缺少从该帧到当前帧的连续回放。
3. 光流失效时继续保留旧框；只估计平移，不估计框的尺度变化，而封存伺服用框面积决定冲刺。
4. 反复 start 会重置跟踪状态；停止后仍允许旧推理结果回写。tracker halt 没有发送 stop，模型直到整局结果才恢复 YOLO，最后一局日志已显示跨阶段输出。
5. 交互命令和图像线程没有共同的模型互斥锁；退出清理日志出现 core dump。不能据现有 schema/命令单测声称线程或单模型运行可靠。
6. 原始图像/哈希与每次决策未一一保存，所需的“看见什么→选中谁→如何飞”审计链仍不完整。

**这些实现问题足以否决当前候选，不能据此否决“九格初始化 + 非语义跟踪”架构。** 本轮止损于实现质量门，不再启动新局。重新投入前应先修复这些点，用真实帧离线验证传图、定位和跟踪，再决定是否值得重开 3.2。

## 6. 加分覆盖与 3.3

4.3 表格是九格目标识别 10 分；4.4(5) 原文针对穿框感知窗口/反馈的扣分要求，本轮气球窗口沿用这一展示标准，并未证明穿框窗口加分合规。补充 FAQ 明确要求全类别识别且混用 YOLO 不加分；**保守按完整 10 分的硬性门槛处理**。当前方框仍由原 YOLO 路径识别，障碍物、起降标识等没有九格验证，提示词列出类别不等于覆盖。

3.1 仍是开发/诊断结果：原视角蓝色可辨认 14/20，模型命中 4/14，标签非完全盲标。未补齐该缺口。本轮红紫蓝各 1 局的窗口验收没有完成，红紫蓝各 ≥3 局的前后回归也没有开展。[3.3 报告](../multimodal_3_3/REPORT.md)标为未验证。建议保持封存部署，不采用本轮候选，不申报该 10 分已经获得。

## 7. MD5 与回滚完成状态

| 对象 | MD5 / 状态 |
|---|---|
| 测试末版 mission_once | `9e59ada4270b086f15e6133dc854cedb`，仅归档 |
| 测试 bt_ros | `9a1e8d2a5913968b1c2300cad1dc02f7`，已回滚 |
| 原 mission_once / 已恢复 | `fca24bf1142ca8cddfb9e8d39c387a43` |
| 原 bt_ros / 已恢复 | `9b1cefe9dfa431418435f7f8f63a60ed` |
| 原 launch / 未改 | `5550c580a4822e773a331bcef11f0c47` |
| 起飞重试头文件 / 保留候选 1 | `c415ddd8243afcc64c181be45bdac5e3` |
| 封存 VisualServo.cpp / 未改 | `a63b57fa127a23cd8bb8e647f078ff21` |
| 测试插件 | `e59a1cde93b0fb7ecd9b91b50240e3ec`，已移入备份目录，不在自动加载目录 |

10 月 24 日恢复了源码并删除新增 tracker 源文件，但回滚复核不完整：构建系统没有删除旧 `.so`，且 `cp -p` 的旧源码时间戳导致编译器跳过 bt_ros 重建，二进制仍引用新节点。10 月 25 日用户确认无人使用后，已把插件移到 `/home/ubuntu/multimodal_3_2_backup_20261023T224616/multimodal_target_tracker.rejected.so`，`touch bt_ros.cpp` 后重新编译并直接检查二进制：含 `<TargetTracker object_name`，不含 `<MultimodalTargetTracker`；最终 bt_ros 二进制 MD5 为 `abb5c49eb21b1b333d88677def4921ab`。这才完成代码/二进制一致的回滚。该次核对服务器没有活动 bt_ros、没有正式试验锁；未启动仿真或试验。旧仿真锁保留，不冒充运行就绪状态。

原始备份：`/home/ubuntu/multimodal_3_2_backup_20261023T224616/`。[归档部署脚本](patches/deploy_multimodal_3_2.sh)默认拒绝部署失败候选；[回滚脚本](patches/rollback_multimodal_3_2.sh)含 MD5 检查、插件清理和重新编译。人工等价命令（在服务器、无活动任务时）：

最终原始核对输出：[rollback_verification.txt](evidence/rollback_verification.txt)；重新编译原始日志：[rollback_build.log](evidence/rollback_build.log)。

```bash
cp -p /home/ubuntu/multimodal_3_2_backup_20261023T224616/mission_once.py /home/ubuntu/model/mission_once.py
cp -p /home/ubuntu/multimodal_3_2_backup_20261023T224616/bt_ros.cpp /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp
rm -f /home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/perception/multimodal_target_tracker.h
rm -f /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp
# 如旧插件仍在，移入上述备份，避免 bt_ros 自动扫描到它。
touch /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp
source /opt/ros/noetic/setup.bash
cd /home/ubuntu/catkin_ws
catkin_make --force-cmake --pkg mission_pkg -j2
md5sum /home/ubuntu/model/mission_once.py /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp
strings devel/lib/mission_pkg/bt_ros | grep -F '<TargetTracker object_name'
```
