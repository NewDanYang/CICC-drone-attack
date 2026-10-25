# 3.2 第二次实施：真实图像接入、窗口与三色控制演示

日期：2026-10-25 至 10-26，北京时间。本轮从封存部署重新生成候选，首轮错误接入的四次红色局与[原报告](REPORT_first_attempt.md)保留，不混入本轮样本。

**已完成真实图像接入及红/紫/蓝各 1 局的窗口—识别—控制证据链。它只证明识别确实参与控制，不代表气球成功率或完整 10 分通过。** 演示中紫球漏击、蓝局额外删球、紫色跟踪漂移均保留；是否采用必须看独立 [3.3 固定版本回归](../multimodal_3_3/REPORT.md)。

## 1. 架构与改动面

先完成[方案比较与逐次决策](architecture_decision.md)，再实施对应修订：拒绝“九格确认＋YOLO 跟踪”，也拒绝为秒级模型重写封存伺服。选用九格独立完成气球语义与初始区域选择，非语义 CSRT 传播其框，继续使用原 VisualServo。

最终路径：sensor1 原始 RGB → 同一个 `mission_once.py`/九格模型实例 → 16 个均匀重叠视图的九格语义 → 局部阳性区域并集 → 至多 8 个无类别图分割区域 → 九格再次识别各区域的原始像素 → CSRT 时序回放/尺度更新 → `MultimodalTargetTracker` → 原 `pixel_target`/VisualServo。区域以自身原始 RGB 输入，其余区域置黑，不能因矩形包围框碰巧含另一气球而给背景区域赋色。

- 图像实际使用 `image=None; content=[PIL.Image, prompt]`。实际 processor 入口逐项检查恰有 1 张图片，保存源图、区域 PNG、像素/文件 SHA256、原回答、时间与决策 ID。
- 模型只加载一次；文本与图像共享同一模型锁。真实输入为 `/rflysim/sensor1/img_rgb`，`bgr8`、640×480、step=1920，通道转换有检查。
- CSRT 从识别原帧回放至当前帧；使用实际跟踪帧的时间，不把推理结束时间冒充观察时间。帧龄≤0.35 s、语义龄≤12 s，间隔/失配/超龄输出无效。确认只更新该观察的采集时间，不用旧 bbox 覆盖当前几何。
- session/track ID 隔离启动、停止、确认和在途结果；击球期间 YOLO 门控关闭，候选不读其 objects、HSV 或世界真值。离开阶段恢复原识别门控。
- BT 只替换一个 tracker 标签；VisualServo 状态机、安全边界、航点、方向 A/B、起飞优化 1 和等待优化 2 保持原字节/原结构。[源码审计](evidence/v2/source_audit.json)验证入口命令辅助函数 AST 不变、BT 恰为标签替换、包内 MD5 全部符合 manifest。
- 主线程显示实际跟踪帧；独立观察器从真实 X11 窗口取图，中心画面全黑的截图拒绝计数。旧紫色 demo4 的 1 张黑图没有算作展示通过。

`obj.score=1` 是已通过离散语义门的接口标志，不是经过校准的模型置信度。局部图分割没有类别输出，但属于几何辅助，须如实向裁判展示，不能把工程解释当成裁判认可。

## 2. 三色演示：逐项核对

三局算法一致，候选 manifest SHA256：`f0eb35a145470c6015627227a994c6a34cc9e701412c2bff1802797dccd1eaae`。每个 processor 项实际含 1 张图，三局图片计数违规均为 0；一个源帧会产生多个分块/区域样本，下面的“图像项”不是独立帧数或识别准确率。

| 颜色 / 正式目录 | processor 图像项 | 非空模型决策 | 坐标消费日志 / 匹配决策 | 实际非黑窗口 | 总用时 s | 物理结果 |
|---|---:|---:|---:|---:|---:|---|
| 红 `20261026T032804_red_A0` | 614 | 7 | 14 / 4 | 2 | 124.784 | 未知：飞后 GC 后 UE 崩溃，缺对象结果 |
| 紫 `20261026T033549_purple_A0` | 555 | 7 | 20 / 3 | 3 | 136.366 | 三球均保留，明确漏击 |
| 蓝 `20261026T031138_blue_A0` | 560 | 15 | 31 / 12 | 4 | 142.569 | Actor 3→1，至少一次额外删球；删球颜色未知 |

原生观察器三局都报 `bt_success=true`、hit 状态空。外围 `Timeout/ForceSuccess` 和旧观察器未识别新 tracker 使其不能作为物理命中证据。上述三局安全边界事件均为 0，但样本小，不能据此证明安全性不变。

可逐条重放的链见包内 `control_links.json`，人工核对见 [demo_review.json](evidence/v2/demo_review.json)：

- **红 `498283974fcf`**：源图由九格给出红球区域，回放后 `center=(370,323)`；原伺服 `ALIGN err=(50,83)`、向负 yaw 修正并下降，随后线上 body frame 指令记录 `vz=-0.3`、负 yaw_rate。[真实窗口](evidence/v2/review/red_window.png)框住红球。
- **紫 `4e155bb9db22`**：真实[窗口 2](evidence/v2/review/purple_window.png)框住右侧紫球；消费 `center=(502,229)` 后 `ALIGN err=(182,-11)`，线上 yaw_rate=-0.5。后续窗口 3 仍框住紫球；其他时刻没有持续可靠跟踪。
- **蓝 `6b0208e5abda`**：[真实窗口](evidence/v2/review/blue_window.png)框住蓝球；同一 decision/session 关联到像素消费、原伺服及随后线上指令，完整原记录在该局 `control_links.json`，没有用假框或源图重新绘制图冒充 X11 截图。

**反例：紫局早期 `beb8eec5c343` 漂移到墙面**，[原截图](evidence/v2/review/purple_drift_counterexample.png)仍被消费并产生修正。它是候选的实际缺陷，不能因后续重新找回紫球就忽略；“非黑截图”与“目标框正确”是两个不同的检查。

## 3. 开发失败完整保留

本轮共 11 个候选调试/演示局、1 个封存诊断基线局。前三色最终演示单列；所有开发局不进入 3.3 分母。表中简称对应 `multimodal_v2_<简称>_20261026`；完整目录、正式试验名及原生 CSV 在[自动复算结果](evidence/v2/development_summary.json)和[原始行](evidence/v2/development_summary.csv)。

| 简称 | 版本/问题 | 图像项 | 消费 / 非黑窗口 | 总用时 s | 飞后 Actor |
|---|---|---:|---:|---:|---|
| demo_red | 三轮细分、原线程配置 | 544 | 0 / 0 | 300.117 | 3→3，4 次边界 |
| diagnostic_baseline_red | 封存诊断对照 | 0 | 原 tracker / 不适用 | 128.076 | 3→2，真实帧见红球接近后消失 |
| demo2_red | 细分、torch 2/1 线程 | 656 | 0 / 0 | 170.338 | 3→3 |
| demo3_red | 阳性窗口交集、细化拒绝 | 624 | 0 / 0 | 154.335 | 3→3 |
| demo4_red | 增加细化失败回退 | 592 | 0 / 0 | 205.810 | 3→3 |
| demo_purple | 肯定回答无颜色，尚未追问 | 528 | 0 / 0 | 214.228 | 3→3 |
| demo2_purple | 已追问，几何框选错背景 | 551 | 0 / 0 | 129.805 | 3→3 |
| demo3_purple | 图区域版，超界适配误判丢失 | 560 | 0 / 0 | 137.951 | 3→3 |
| demo4_purple | 修正部分框裁剪，窗口被遮挡 | 543 | 5 / 0 | 134.532 | 3→3；1 张全黑截图拒绝 |
| demo_blue | 最终算法，修正截图工具 | 560 | 31 / 4 | 142.569 | 见三色演示 |
| demo5_red | 同一最终算法 | 614 | 14 / 2 | 124.784 | 见三色演示 |
| demo5_purple | 同一最终算法 | 555 | 20 / 3 | 136.366 | 见三色演示 |

除首个红色超时局外，上表其余局的原生边界事件均为 0。第一次红色与诊断基线只支持资源争用的待验假设，不能把模型线程限速写成已证明的根因修复。真实帧回放另确认了两个具体实现问题：GrabCut 曾选中地面；CSRT 成功但部分超界曾被适配器错误清掉。这些与“模型本身完全不能识别”不同，修复前后证据分别保留。

## 4. 测量工具与结论边界

红色 demo5 飞前曾用 SDK 只读 `reqObj` 查询三个 Actor 以标记本实例颜色，接收线程已关闭；飞行 124.784 秒结束后才发一次 GC。1 秒后 UE 在 `ARflyHUD::processReqDataLoop` 发生 SIGSEGV，[原日志](evidence/v2/red_demo5_gc_crash.log)保留。预注册对象请求与 GC 的交互是当前解释，未独立复现或取得供应商内部证据，不能宣称精确根因已经证明。现有 SDK 没有可确认的注销接口；不能假设客户端退出就清除了引擎端引用。该局物理结果为 unknown，不改判成功/漏击，不归为算法飞行崩溃。

后续取消所有飞前/飞中载荷请求。3.3 在飞行结束、解除武装、GC 和两次对象列表保存后，才查询存活球的车道颜色，随后完整重启 UE。该测量不进入控制，不跨实例套用 ID。细则见[回归协议](../multimodal_3_3/protocol_v2.md)。

14 项接口/失效保护[检查通过](evidence/v2/guard_checks.log)，只证明时钟、停止、解码、几何门等实现约束，不是视觉准确率或飞行成功率。全部开发真实帧已经用于修改方案，不能当成盲测集。

**范围缺口保持明确**：3.1 仍是开发/诊断结果，蓝色原机位只有 14/20 帧可辨认、模型 4/14 命中，未补正式验收。方框/障碍物/起降标识未完成九格独立替换，其他阶段仍有原 YOLO；按全类别为硬门槛的保守口径，不能申请“完整 10 分已经通过”。4.4(5) 原文处于穿框条目，本轮气球窗口不等于完成穿框感知加分演示。

## 5. 原始证据、部署与回滚

证据索引和解包复算命令见 [evidence/v2/README](evidence/v2/README.md)。每局包含全部模型源 PNG/实际区域输入、全部窗口、原始 JSONL、原生遥测/规划 CSV、部署 MD5；全量相机 JPEG 在服务器保留，Git 包抽取每十张中的一张并对全部原件给 SHA256，不能把抽样包误称全量相机包。服务器原始 session 均在 `/home/ubuntu/tcei_baseline_tools/results/`，正式局在 `formal_trials/`。

部署包全部原始字节 MD5： [v2/manifest.json](v2/manifest.json)。包 SHA256 为 `54ccbd05d8d552f52392aa1c194c71c5aa968b6ef0685aa68e9dfce1d8fa157d`；最终算法源与三色演示一致，后续只完善离线分析与编排测量。

| 文件 | 原/封存 MD5 | 实验候选 MD5 |
|---|---|---|
| mission_once.py | `fca24bf1142ca8cddfb9e8d39c387a43` | `de03cd1a5687f7bc0664ea52f3cd095f` |
| bt_ros.cpp | `9b1cefe9dfa431418435f7f8f63a60ed` | `9a1e8d2a5913968b1c2300cad1dc02f7` |
| localizer.py | 新增 | `8d329caed84b8d1c7eb4c7c20c3fb06f` |
| geometry.py | 新增 | `58db79f8cb33c10c6bc4d7aad60e54dc` |
| tracking.py | 新增 | `96a1683400e98c7f8fb898a53f3f2434` |
| runtime.py | 新增 | `d6f65f166b8ecda4de0b7c1126fa3c2e` |
| MultimodalTargetTracker.cpp | 新增 | `092fe8df8991ef5e2bb510ce5650c731` |
| llm_mission.launch | `5550c580a4822e773a331bcef11f0c47` | 不变 |
| 起飞重试头文件（候选 1） | `c415ddd8243afcc64c181be45bdac5e3` | 不变 |
| VisualServo.cpp | `a63b57fa127a23cd8bb8e647f078ff21` | 不变 |
| VisualServo.h | `d3324b0458b2160102f9bbf44546d035` | 不变 |

备份 `/home/ubuntu/multimodal_v2_backup_20261026T0009`；实验包 `/home/ubuntu/multimodal_v2`。在已确认无人占用、无正式锁且 PX4 解除武装时，使用带 MD5、精确 PID、串行构建与二进制检查的脚本：

```bash
# 实验候选；不是正式比赛部署建议
bash /home/ubuntu/multimodal_v2/tools/switch_condition_v2.sh candidate /home/ubuntu/multimodal_v2_backup_20261026T0009
# 完整回滚：恢复原入口/BT，移出新增模块、源码与插件，touch 并重编译，重启独立新场景
bash /home/ubuntu/multimodal_v2/tools/switch_condition_v2.sh baseline /home/ubuntu/multimodal_v2_backup_20261026T0009
# 核对源码、插件存在性及实际二进制；构建脚本另外检查实际 BT 标签
/usr/bin/python3 /home/ubuntu/multimodal_v2/patches/deploy_v2.py status /home/ubuntu/multimodal_v2_backup_20261026T0009
```

最终部署状态与回滚核对原件统一记录在 [3.3 报告](../multimodal_3_3/REPORT.md)，不能用本文三色接通结论替代可靠性采用结论。
