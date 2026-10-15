# 1.2 击破时刻与 UE Actor 计数延迟（2026-10-16）

## 方法与适用范围

复用 [1.1 的九局三球基线](../hit_balloon_part1_1.1/REPORT.md)，按真实相机帧中目标色块最后出现、首次消失的两帧给出候选时间区间；日志确定当时是 APPROACHING、SPRINTING，还是两者交界。该区间的宽度为 1.0–1.1 秒。**画面消失不等于精确碰撞时间**：球可能离开视野或被遮挡，必须与三球开局及结局 Actor 减少一起解读。第 3 局蓝球镜头转向，既不能确认目标球被击破，也不能给出合格的击破时刻；保留这一反例，没有补造 ±2 秒数据。逐局原始值见 [timing.csv](timing.csv)、[1.1 关键帧和 ROS 日志](../hit_balloon_part1_1.1/evidence/)。

九局中，7 局有目标色相机消失的候选区间，另第 9 局蓝球还拍到破裂火花，共 8/9 有目标色证据。冲刺发生于 3/9 局（第 2、4、5 局），其中第 4 局消失在 SPRINTING 内，第 2、5 局的 1 秒采样区间横跨冲刺边界。**至少 5 局在未冲刺时已接近或碰到目标**（第 1、6、7、8、9 局），故只修改 SPRINTING 不足以涵盖所有碰撞。第 3 局只能记录视觉候选，无法归类为击破。

逐局越界对齐：第 2 局首次越界落在目标消失的相邻两帧之间，先后顺序无法分辨；第 4 局两次越界均在 VisualServo 前；第 6、9 局首次越界分别比画面消失晚约 54、46 秒。其余 5 局没有越界日志。因此不能将全部 6 次越界归因于“冲刺撞球后继续飞”。

## 强制 GC 对照

使用 `UE4CtrlAPI().sendUE4Cmd("obj gc")`，服务器 UE 日志确有 `Collecting garbage and resetting GC timer`；命令文档也列于 [Epic UE 5.4 发行说明](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5.4-release-notes?application_version=5.4)。同一采样器在控制和强制 GC 两局均约 1.7 秒取一次 `obj list class=BP_Balloon_C`，样本分别 155、159 条，采样错误都是 0。两局均为新场景三球开局的紫球正式试验，**不是随机分组或重复多次的性能对照**。

| 条件 | 相机目标最后可见→首次消失 (UTC) | 冲刺开始 | UE 首次计数 3→2 | 与冲刺开始相差 | 结局 |
|---|---|---|---|---:|---:|
| 不发送 GC，1 局 | 16:46:23.785→24.863 | 16:46:24.215 | 16:46:44.197 | 19.981 秒 | 3→2 |
| 冲刺后强制 GC，1 局 | 16:52:02.774→03.774 | 16:52:03.073 | 16:52:03.939 | 0.865 秒 | 3→2 |

强制 GC 局的第一条 `obj gc` 在冲刺开始后 0.436 秒发出，UE 在约 0.009 秒后记下实际回收，Actor 计数在第一个后续采样点降到 2。控制局直到冲刺后约 20 秒才在 Actor 列表中降到 2。这两例支持 **GC 可以缩短本场景 Actor 列表的回收延迟**，不能证明 GC 时刻就是物理击破时刻，也不能据 1 对 1 样本估计成功率。详见 [pair_summary.json](pair_summary.json)、[control_events.jsonl](control_events.jsonl)、[gc_events.jsonl](gc_events.jsonl)。

按题意另跑一局持续采样：每 1–2 秒先发送 GC 再查询 Actor，共 164 次 GC、164 个样本、0 个采样错误，间隔中位数 1.831 秒。该紫球局没有冲刺，计数在 17:01:14.772 从 3→2，17:01:25.978 又从 2→1，最终 **3→1**；这再次暴露了误击风险。详见 [continuous_summary.json](continuous_summary.json)、[continuous_events.jsonl](continuous_events.jsonl)。记录“计数变化所在采样区间”时，上限由前后两次查询决定，约 1.8 秒；持续发送 GC 本身可能影响仿真时序，所以这局只验证测量工具，不纳入 1.1 九局基线或后续算法验收。

## 原始位置、回滚与结论边界

服务器对照试验：`/home/ubuntu/tcei_baseline_tools/results/hit_balloon_gc_comparison_20261016T004306/`；持续采样试验：`/home/ubuntu/tcei_baseline_tools/results/hit_balloon_gc_continuous_20261016T005802/`。两目录的 `*/events.jsonl` 包含每次采样、GC 命令及 ROS 事件，`*/trial_dir.txt` 指向正式试验原始目录，其 `scene_snapshots.jsonl`、真实帧与遥测保留在服务器。GC 工具只在试验编排进程里发 UE 命令，未改 ROS 源码；停止工具即回滚，命令：`pkill -f '[g]c_timing_probe.py'`（先确认不是别人运行的采样器）。原始数据应保留。结论只适用于这些三球初始、A0 档位的 2+1 局紫球对照以及 1.1 的九局图像时间窗，不外推到所有颜色和所有碰撞。
