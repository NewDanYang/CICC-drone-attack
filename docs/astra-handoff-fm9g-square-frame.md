# Astra 交接：方框（square_frame）九格识别——部署+真实验证

开始前请读：`v4_innovation_timing/multimodal_6_0_square_frame_scope/REPORT.md`（规则核对、延迟风险、接入方式设计）、`v4_innovation_timing/multimodal_6_2_square_frame_impl/REPORT.md`（实现说明）、`v4_innovation_timing/multimodal_6_2_square_frame_impl/frame_locator.py`（已写好的模块，离线审查过，没有实测过）。

## 0. 背景

气球那条线目前搁置（见 `multimodal_6_1_search_coverage/REPORT.md`：已知可用招数都试过或排除了，没有新思路前不再碰）。按计划转向方框穿越障碍的九格识别——这是"最小得分任务"，风险比气球小很多（方框是静止目标，一次性定位，不存在气球那套"框追不上变大目标"的问题）。

这次任务**只做方框（`square_frame`），不碰气球**，我已经把检测模块写完并离线审查过（复用气球侧已验证的检测算法，没有修改任何已冻结的 `presence.py`/`runtime.py`），但从未在真实仿真里跑过——这次任务的目的是把它部署、跑通、拿到真实验证证据。

## 1. 硬约束（不变，同以往）

1. 不改 `VisualServo`、安全边界、launch 速度、航点、A/B 方向、用时优化。
2. 不改气球相关代码路径（`runtime.py`、`presence.py`、`multimodal_target_tracker.cpp`）——这次只加一个新文件、改两行 `mission_once.py`、改一个 YAML 配置项。
3. 改动前必须记录涉及文件的 md5（`mission_once.py`、`detection_params.yaml`），报告里给出回滚命令。
4. 用服务器前检查试验锁；每局开始前完整重启仿真环境。
5. 口令只用环境变量。

## 2. 任务：部署 + 跑通 + 拿真实对照证据

### 2.1 部署（三步，具体位置已在 `multimodal_6_2_square_frame_impl/REPORT.md` §1.3 写清楚）

1. 把 `frame_locator.py` 放到候选目录 `/home/ubuntu/multimodal_v2/v2/`（和 `runtime.py`、`presence.py` 同级，它用 `from .presence import NativePresenceSweep` 相对导入，需要这个目录本身是个 Python 包——确认 `fm9g_perception` 目录下有无 `__init__.py`，没有就不需要加，用的是这个目录本身作为包）。
2. 在 `mission_once.py` 第 234-235 行（`model_lock = threading.Lock()` / `bridge = PerceptionBridge(...)` 那两行）后面加：
   ```python
   from fm9g_perception.frame_locator import FrameLocatorBridge
   frame_bridge = FrameLocatorBridge(model, tokenizer, processor, model_lock)
   ```
   并在现有的清理/退出逻辑里加 `frame_bridge.stop()`（具体位置你核对当前文件，报告里已有的 `bridge.stop()` 之类的清理代码附近）。
3. `object_det/config/detection_params.yaml` 的 `target_classes` 去掉 `"square_frame"`，只留 `"red_balloon"`。改之前记录原文件 md5。这一步需要重启 `det_color_conda.sh` 对应的节点（通常随整个仿真环境重启一起生效）。

### 2.2 单独验证（不要先跑完整大矩阵，先确认链路通）

先跑 1-2 局（随便什么颜色，这一步只关心过框阶段），确认：

- `frame_locator.py` 的 audit 目录（默认 `/home/ubuntu/tcei_baseline_tools/results/multimodal_frame_v1/<时间戳>/`）正常生成，`audit.jsonl` 里能看到 `ready`、`model_source`、`decision`、`presence_sweep` 事件；
- rosout 或行为树日志里 `TargetLocator` 真的进入 `SUCCESS`（不是一直卡在"Collecting frames: N/10"）,拿到的 `frame_center` 坐标看起来合理（不是乱飘到场景外）；
- `/multimodal/frame_debug_image` 话题上能看到画了框和置信度的调试画面；
- 气球阶段开始后（`[VisualServo]: Visual Servo Started` 或更早的 `MULTIMODAL_STAGE_START` 日志出现时），`frame_locator.py` 的 audit 里出现 `deactivated` 事件，确认它真的停止了，没有继续占 GPU。

如果这一步任何一项不对，停下来报告现象，不要往后跑更多局——先把链路本身跑通再谈采样。

### 2.3 对照验证（链路通了之后）

链路确认正常后，跑至少 **3-5 局候选（九格方框识别）vs 封存基线（YOLO 方框识别）对照**，参照 5.7/5.12 阶段 D 的记录方式：每局重启仿真环境、记录 `TargetLocator` 耗时（从节点开始到 `SUCCESS` 的秒数，预计会比 YOLO 慢 3-6 秒，这是已知代价不是故障）、记录飞行阶段是否正常完成（起飞→过框→二维码→逆序过框）、记录候选和基线每局是否都真的完整走完这几个阶段。

**不需要**像气球阶段 D 那样做 Actor 删除判定（方框不是会被摧毁的目标），用"过框阶段是否正常完成+用时"做对照就够。

## 3. 不要做的事

- 不要顺手"优化"或"修复"方框定位算法——这个模块还没有任何真实数据,先如实跑出来看效果,不要在没有证据之前改代码。
- 不要把气球相关代码路径也动了。
- 不要因为单局看起来好/不好就下结论,按 AGENTS.md 的 3-5 局最低样本要求来。
- 如果方框模块在真实仿真里暴露出任何设计缺陷(比如和我文档里写的行为不一致),如实记录现象,不要自己改 `frame_locator.py` 的核心逻辑——报告给我,我来决定怎么改。

## 4. 交付物

新目录 `v4_innovation_timing/multimodal_6_3_square_frame_flight/`,内容:

1. 部署步骤实际执行记录(文件改动、md5 前后对照、回滚命令);
2. 链路验证结果(§2.2 四项逐条打勾或记录异常);
3. 候选 vs 基线对照局表格(至少 3-5 局候选,对应基线局数);
4. 原始证据(rosout、`frame_locator.py` 的 audit 目录、每局耗时)。

提交到当前分支 `research/fm9g-presence-sweep`,不要合并到 `main`。完成后告诉我,不需要自己下"是否可以正式接入"的结论——这个判断我来做。
