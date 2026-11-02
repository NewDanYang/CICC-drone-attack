# 6.2：方框识别模块实现完成——离线设计到位，部署+实飞交给 Astra

日期：2026-11-02。纯离线实现（写代码、读部署目录核对接入点），没有改动服务器上任何正在运行的文件，没有起飞。按计划完成"准备方框"这一步，研究/设计我自己做完，接下来的真实部署和飞行验证按约定交给 Astra。

## 1. 做了什么

### 1.1 新模块 `frame_locator.py`

`FrameLocatorBridge` 类，完整实现见同目录 `frame_locator.py`。关键设计点：

- **复用已验证的检测算法，不碰已冻结的 `presence.py`**：方框定位用的是和气球 `acquire()` 完全相同的"九宫格粗定位 + 两阶段边缘扫描"流程，但直接调用 `NativePresenceSweep` 已公开的辅助方法（`square`/`crops`/`sweep_imgs`/`edge_box`/`call`）自己拼出来，而不是改 `acquire()` 本身——因为 `acquire()` 不返回置信度分数，而 `common_msgs/Obj.score` 字段需要这个分数（`TargetDetectorBase` 用 `score >= confidence_threshold` 过滤）。

- **发现并避开了一个真实的耦合坑**：最初设计想直接复用气球侧已经构建好的那个 `NativePresenceSweep` 实例（图省事）。但读了 `presence.py` 的 `call()` 方法才发现，它的每次调用都会先检查传入的 `active(epoch)` 回调——而气球那个实例的 `active` 回调是绑在气球会话状态上的（`PerceptionBridge.active`），在没有气球会话时恒为假。方框识别恰好主要发生在**气球会话开始之前**（起飞后、过框阶段），如果真的共用那个实例，每次方框检测调用都会被扔出 `RuntimeError("presence inference became inactive")`。**修复**：给方框模块建了自己的 `NativePresenceSweep` 实例，自己的 epoch/active/audit，但传入和气球侧**完全相同**的 `model`、`tokenizer`、`processor`、`model_lock` 对象——这样仍然只加载了一份模型权重（满足"只加载一份模型"的硬约束），只是多了一个很轻量的 Python 包装对象，GPU 调用仍然通过同一把 `model_lock` 串行，不会和气球侧并发抢卡。

- **发布目标：复用已有的 `/objects` 话题，不新建话题，不新建 BT 节点类型**。查过 `TargetDetectorBase`（`TargetLocator` 的基类）的源码：它只按 `class_name == object_name and score >= confidence_threshold` 过滤，完全不检查 `header.frame_id` 或任何会话标识（这点和气球侧的 `MultimodalTargetTracker` 不一样，气球那边自己写了新 C++ 节点、新话题、按 `frame_id` 前缀校验）。这意味着方框检测结果直接发到 `/objects`，用和 YOLO 当年完全一样的 `common_msgs/Objects` schema，`TargetLocator` 一行代码都不用改就能消费——**零 C++ 改动，零新建节点类型**。

- **自动关闭，不新增 ROS 消息**：方框模块订阅已有的 `/multimodal/balloon_target` 话题（气球侧 `MultimodalTargetTracker` 本来就会在气球阶段开始时发一条 start 消息），第一次收到任何消息（start 或 stop）就永久停止方框检测——因为按生成的行为树结构，方框识别只会发生在气球阶段开始之前，气球一旦开始就不需要方框模块继续占用 GPU 时间了。不需要新增任何消息类型。

- **感知窗口**：按 4.4(5) 细则要求的 bbox 可视化窗口，另开一个 `/multimodal/frame_debug_image` 话题（不跟气球侧的调试窗口混在一起），画框、置信度、随时间推送。

### 1.2 需要的配置改动（尚未应用，留给 Astra 做+验证）

`object_det/config/detection_params.yaml` 的 `target_classes` 需要去掉 `"square_frame"`（只留 `"red_balloon"`），否则 YOLO 和 FM9G 会同时往 `/objects` 发 square_frame 结果，变成"混用"而不是"九格独立识别"——这正是 FAQ 5.4 明确不算加分的情况。这是纯 YAML 改动，不需要重编译，但需要重启 `det_color_conda.sh` 节点才会生效，且必须在真实仿真里验证改完之后 `TargetLocator` 还能不能正常收到方框位置——这类"改配置+需要重启+需要真实验证"的工作按约定交给 Astra。

### 1.3 集成点（写给 Astra 的精确位置，不是泛泛而谈）

部署目录 `/home/ubuntu/multimodal_v2/v2/mission_once.py` 第 234-235 行：

```python
model_lock = threading.Lock()
bridge = PerceptionBridge(model, tokenizer, processor, model_lock)
```

在这两行后面加一行，构造方框模块（两者共享同一个 `model`/`tokenizer`/`processor`/`model_lock`）：

```python
from fm9g_perception.frame_locator import FrameLocatorBridge
frame_bridge = FrameLocatorBridge(model, tokenizer, processor, model_lock)
```

`frame_locator.py` 需要和 `runtime.py`/`presence.py` 放在同一个 `fm9g_perception` 包目录下（它用 `from .presence import NativePresenceSweep` 相对导入）。`main()` 函数退出前（现有代码已有 `bridge.stop()` 之类的清理逻辑，具体位置需要 Astra 核对当前文件）也要加 `frame_bridge.stop()`。

## 2. 还没做、留给 Astra 的事（"大任务"）

1. 把 `frame_locator.py` 部署到候选目录，按上面的两行改 `mission_once.py`，按 §1.2 改 `detection_params.yaml`（先 md5 记录原值）。
2. 真实仿真验证：先单独起飞到过框阶段，确认 `TargetLocator` 真的能从方框模块的发布里拿到有效坐标并给出 SUCCESS（而不是一直卡在"收集帧"状态）；确认调试窗口里能看到方框的框和置信度；确认气球阶段开始后方框模块真的停止发布（检查 audit.jsonl 的 `deactivated` 事件）。
3. 至少 3-5 局真实对照（有方框模块 vs 封存 YOLO 基线），按 AGENTS.md 的证据纪律，不能凭 1 局成功下结论。
4. 如果验证通过，再考�核算要不要加第 2 次反向识别（见 6.0 报告，规则不强制，是加分材料扎实度的权衡）。

## 3. 风险提示（写给 Astra，也写给用户）

- 方框是静止目标、一次性定位，不存在气球那条线反复踩坑的"框追不上变大目标"类问题，风险模型比气球简单得多。
- 但 `TargetLocator` 需要攒够 10 个有效样本才给结果（硬编码常量，详见 6.0 报告 §2），九格检测比 YOLO 慢，预计会让这个阶段多花 3-6 秒——这是已知、可接受的时间成本，不是故障，不要误判为 bug 去"修"。
- 这次改动涉及修改一个正在使用的 YAML 配置文件（`detection_params.yaml`）并需要重启节点验证，按 AGENTS.md §3.3，改之前要留档案（备份+md5），报告里要给出回滚命令。

## 4. 代码位置

`frame_locator.py` 放在本报告同目录，尚未提交到服务器任何路径，等 Astra 验证环境就绪后由她部署。
