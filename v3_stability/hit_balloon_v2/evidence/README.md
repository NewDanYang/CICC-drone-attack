# 2026-10-12 场景证据索引

每个 `*_scene_snapshots.jsonl` 是对应正式试验目录中同名文件的拷贝；每行包含 UE PID、日志 inode 与字节范围、原始 `obj list class=BP_Balloon_C` 行、Actor ID 集合和时间。`*_judgement.json` 由同目录 `tools/judge_hit.py` 对服务器原始 `*telemetry.jsonl` 与场景快照生成。

**判读器 v3 纠错**：首版把任一 Actor 消失误算为请求颜色，v2 又错误地把 Actor 编号排序当作跨场景稳定颜色映射。独立 UE 实例 210064 只剩最低编号 `...1415` 时，`20261012T101832_142616Z_0080.jpg` 实际拍到蓝球，同刻颜色分类 `blue=1460, purple=0`；这与旧排序“最低=紫”直接矛盾。v3 只接受 `tools/actor_scene_calibrations.json` 中针对**该 UE 实例**的映射。未校准场景的一次 Actor 删除降为 `unknown`。旧首版 JSON 在 `20261012T171720_red_judgement_original.json`；错误排序配置保留为 `actor_rank_calibration_rejected.json`；服务器各局旧判读保留 `judgement_v1.json` 和 `judgement_rank_v2.json`。Actor 颜色仍由同场景图像、检测与 Actor 集合变化推断，不是 UE 原生颜色属性。

| 试验目录（服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/` 下） | Actor 数变化 | 判读 | 时间说明 |
|---|---|---|---|
| `20261012T155013_red_A0` | 3→3→3 | unknown | 场景 PID 53307 没有直接颜色映射；最后快照距结束约 189 s |
| `20261012T155603_purple_A0` | 3→2 | unknown | 场景 PID 53307 未校准，不能把单个删除归属为紫球 |
| `20261012T160158_blue_A0` | 2→2→1 | unknown | 场景 PID 53307 未校准，延迟减少一个仍不能归属为蓝球 |
| `20261012T161302_red_A0` | 3→2→2 | unknown | 场景 PID 88912 未校准；红球跟踪不排除途中误碰别色 |
| `20261012T162215_red_A0` | 3→3→2 | true（颜色由单目标跟踪归属） | 红区入场 yaw=3.14159；任务结束即刻未减少，125 s 后少一个；同一 UE PID 104757 |
| `20261012T162655_purple_A0` | 2→1→1 | true（颜色由单目标跟踪归属） | 与上一行同一 UE 实例；紫色单目标有效跟踪，冲刺后即时少一个 Actor，125 s 后不变 |
| `20261012T163138_blue_A0` | 1→0→0 | true（颜色由单目标跟踪归属） | 与上一行同一 UE 实例；UE 在结束即刻原始日志已答 `0 Objects`，解析器修复后无插入任务地回补两次零 Actor 快照 |
| `20261012T163949_red_A0` | 3→1→1 | unknown | 独立新场景，红任务中两个 Actor 消失，违反单色归属条件；相机拍到蓝球进入航路 |
| `20261012T164542_purple_A0` | 1→1→1 | unknown | 场景 PID 129308 的唯一残留 Actor 未做直接颜色映射；偏心冲刺仍是控制失败证据 |
| `20261012T165314_red_A0` | 3→3→2 | unknown | 新场景，红区全程 z=1.5；0 次红色有效像素，延迟快照少一个最高编号 Actor，不能独立归色 |
| `20261012T170422_red_A0` | 3→3→3 | false | 新场景，分段高度、旧冲刺逻辑；误差 `(126,126) px` 时冲刺，125 s 后无 Actor 消失 |
| `20261012T171054_red_A0` | 3→3→3 | false | 同一场景、仅加冲刺居中门控；偏心时未冲刺，但继续前推丢目标后返回假 SUCCESS |
| `20261012T171720_red_A0` | 3→3→2 | false（v2 修正） | 同一场景、近距离悬停对齐后红球居中冲刺；延迟消失的是编号居中的蓝球，红球 Actor 仍在 |
| `20261012T173621_red_A0` | 2→1→1 | true（同场景校准） | 红球无冲刺，但接近面积峰值 38.5%；最高编号删除；该局 `mission_success=false`、降落成功 |
| `20261012T1747_idle_control` | 3→3→3 | 空白对照 | 全新场景 UE PID 210064，无人机始终未解锁，268.6 s 三个 Actor 不变 |
| `20261012T175348_red_A0` | 3→3→2 | true（同场景校准） | 固定偏航测量局；红球冲刺 yaw≈−2.996；整局成功 |
| `20261012T180225_purple_A0` | 2→1→1 | true（同场景校准） | 紫球接近面积 46.7% 后消失；有边界恢复，`mission_success=false`、降落成功；旧排序误判为 false |
| `20261012T181001_purple_A0` | 1→1→1 | unknown | 紫球 Actor 已在上一局消失，本局不能作为紫色算法失败样本 |
| `20261012T181709_purple_A0` | 1→1→1 | unknown | 只剩蓝球；真实相机 `blue_singleton.jpg` 与颜色分类直接支持同场景映射 |
| `20261012T182513_blue_A0` | 1→0→0 | true（同场景校准） | 蓝球是本场景最后一个 Actor；整局成功，结束即刻 0 个 Actor |
| `20261012T183325_red_A0` | 3→2→2 | true（同场景校准） | UE PID 267731；红色有效跟踪 20 次，最高编号 Actor 删除；无冲刺，observer 的 `mission_success=false` |
| `20261012T183848_purple_A0` | 2→1→1 | true（同场景校准） | 同一 UE；紫色冲刺面积 14.36%→54.07%，最低编号 Actor 删除；`mission_success=true` |
| `20261012T184356_blue_A0` | 1→1→1 | unknown（模型错色） | 正式输入蓝球，但模型发布 `hit_balloon:purple`，生成 BT 的目标是 `purple_balloon`；不计入蓝色控制算法分母 |
| `20261012T185145_blue_A0` | 1→1→0 | true（延迟代理判据） | 加模型颜色校验后 BT 正确选蓝；真实相机在 `10:53:36.654Z` 拍到仅存蓝球，任务结束即刻 Actor 仍在，125 s 后删除；冲刺画面为蓝墙，精确碰撞时刻未证实 |

早期红、蓝局的原始即刻快照在服务器相应正式目录中另存为 `scene_snapshots_initial.jsonl`；`late` 行另含 `source_session`，便于核对其来源。后续新局由包装脚本自动取试验前、结束后和 125 s 稳定快照。完整飞行、颜色检测和安全恢复日志保存在各试验目录的 `*telemetry.jsonl`。表中的 `true` 是**同场景颜色校准后的 Actor 删除代理判据**，不是比赛裁判 API 的得分回执；逐色样本数与适用范围以主报告为准。

红球 `20261012T161302_red_A0` 的四张 JPEG 取自真实 `/rflysim/sensor1/img_rgb`，`*_frames.jsonl` 记录原始文件名、各帧 UTC 时间与 MAVROS 里程计：`visual_start` 为 `08:14:37.750Z`（原入场朝向墙面）；`first_detect` 为 `08:14:40.942Z`（搜索转向后气球进入画面）；`sprint_before` 为 `08:14:45.428Z`，`sprint_after` 为 `08:14:46.548Z`。改朝向局 `20261012T162215_red_A0` 的 `visual_start` 为 `08:23:58.594Z`，红球已在画面中央偏右；日志中视觉伺服启动 `08:23:58.270Z`，首次跟踪 `08:23:58.290Z`。JPEG 用于解释入场视角；击破判据仍以 Actor 快照和单色 BT 跟踪为准。

第三轮红球目录的 `red_blue_in_path.jpg`、`red_blue_gone.jpg` 和 `red_close.jpg` 对应真实相机 `08:41:17.961Z`、`08:41:19.962Z`、`08:41:56.179Z`；`red_frames.jsonl` 可追溯原始图名和里程计，`red_color_window.jsonl` 是原始遥测中 `08:41` 的 20 条颜色分类日志。场景判读保持 `unknown`，不会把额外蓝球消失误算为红色的稳定成功。

`20261012T165314_red_A0` 的 `red_visual_start.jpg` 采自 `08:55:14.036Z`，其 `red_frames.jsonl` 记录原始文件名与当时 z≈1.50 m。画面未见红球且整局无红色有效像素；单个 Actor 延迟消失的原因、时间与颜色无直接事件日志，判 `unknown`。`20261012T1753_yaw_probe.log` 记录固定角速度两段各 2 s 的像素与偏航；`20261012T1747_idle_scene_snapshots.jsonl` 是无飞行空白对照。

`20261012T185145_blue_before_2.jpg` 是正式场景真实 `/rflysim/sensor1/img_rgb` 在冲刺前约 1 s 的蓝球画面；`20261012T185145_blue_sprint_start.jpg` 与 `..._sprint_end.jpg` 是同局蓝墙画面。日志中目标面积从 3.0% 跳到 37.7%、59.4%，提示 YOLO/HSV 在墙面产生大框；Actor 删除只在 125 s 稳定快照出现，因此本局 `true` 限于场景删除代理判据，不表示冲刺画面证明了碰撞。校准配置 `tools/actor_scene_calibrations.json` 针对 UE PID 267731 单独记录映射，没有沿用其他 UE 的编号排序。

`aruco_window_summary_20261012.csv` 是 `tools/summarize_aruco.py` 对 19 局服务器原始 `*telemetry.jsonl` 的逐局提取。19 个 ENABLED→DISABLED 窗口均短于 1 秒；其中一局出现一次 `callbacks/s=6.9`，其他 18 局 `rate_samples=0` 表示计时器尚未到每秒采样点，不能当作长窗口不会出现 `callbacks/s=0` 的反证。

## 复机后独立场景回归（2026-10-13 北京）

逐局机器可读汇总见 [`formal_regression_summary_20261013.csv`](formal_regression_summary_20261013.csv)。该表来自正式 CSV、每局 `judgement.json` 和 `scene_snapshots.jsonl`，保留 observer 全局结果、降落及边界次数，不把它们混同于击破代理判据。服务端原始目录均在 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/<目录>/`，仍包含完整 `*telemetry.jsonl`、`mission_once.out`、`observer.out`、`real_frames/`。本仓库的 `*_frames.jsonl` 记录取回 JPEG 对应的真实 `/rflysim/sensor1/img_rgb` 帧名、UTC 时间及位置。

| UE PID | 局序与正式目录 | Actor 数前→即刻→125 s | 逐实例判读 | 实景相机校准样例 |
|---:|---|---|---|---|
| 2773 | `20261012T232400_red_A0` | 3→3→2 | unknown | `red_sprint_start/end.jpg` 见红球；未得到另两色完整映射 |
| 2773 | `20261012T232932_purple_A0` | 2→2→0 | unknown | `purple_sprint_before/mid/end.jpg` 见紫球；同一观察区间少两个 Actor |
| 22370 | `20261012T233628_purple_A0` | 3→3→2 | true | `purple_pre_sprint_1s.jpg`、`purple_sprint_before.jpg`；仅最低编号消失 |
| 22370 | `20261012T234149_blue_A0` | 2→1→1 | true | `blue_approach.jpg`、`blue_late.jpg`；仅中间编号消失 |
| 22370 | `20261012T234717_red_A0` | 1→1→0 | true | `red_approach.jpg`；最高编号最终消失 |
| 53102 | `20261012T235510_blue_A0` | 3→2→2 | true | `blue_first_track.jpg`、`blue_late_approach.jpg`；仅中间编号消失 |
| 53102 | `20261013T000043_red_A0` | 2→2→1 | true | `red_sprint_start/end.jpg`；仅最高编号消失 |
| 53102 | `20261013T000608_purple_A0` | 1→0→0 | true | `purple_approach.jpg`、`purple_close.jpg`；最低编号最终消失 |
| 82946 | `20261013T001446_red_A0` | 3→3→2 | true | `red_approach.jpg`、`red_late.jpg`；仅最高编号消失 |
| 82946 | `20261013T002201_purple_A0` | 2→1→1 | true | `purple_approach.jpg`、`purple_close.jpg`；仅最低编号消失 |
| 82946 | `20261013T002730_blue_A0` | 1→0→0 | true | `blue_approach.jpg`、`blue_close.jpg`；中间编号最终消失 |

上表的图片均带对应目录时间戳前缀（例如 `20261013T002730_blue_close.jpg`），防止不同场景同名混淆。三套可校准新场景共红、紫、蓝各 3/3；PID 2773 两局无法唯一归色，保留各自的 `*_judgement_pre_calibration.json`，没有补猜。PID `22370/53102/82946` 的旧 `judgement_pre_calibration.json` 留在服务器原始目录，新 `*_judgement.json` 是补入本 UE 实例映射后重判的结果。映射见 `../tools/actor_scene_calibrations.json`，不复用其他 UE 实例编号顺序。
