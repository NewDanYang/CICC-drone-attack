# hit_balloon 三色排查与回归（2026-10-12）

## 判据与结论边界

`mission_success`、observer 的 `hit_balloon_status=success` 和 `Sprint completed` 均**不证明气球破裂**：生成的击球 BT 有 `ForceSuccess`，observer 又把冲刺完成当作该阶段成功。本文的 `true` 是更强但仍属**代理判据**：同一 Unreal 进程的完整三球名单经真实相机/颜色日志逐实例校准，单色 BT 目标正确且有有效跟踪像素，任务前后恰有对应 Actor 消失，延迟观察至少 125 s。判读程序为 [`judge_hit.py`](../hit_balloon_v2/tools/judge_hit.py)，校准表为 [`actor_scene_calibrations.json`](../hit_balloon_v2/tools/actor_scene_calibrations.json)。没有比赛裁判的击破事件 API 或 Actor 自带颜色字段，因此不能称为官方得分回执，也不能把 `true` 精确归因于冲刺时刻。

截至本报告所记已完成的试验，跨不同增量版本且有同场景校准的正式样本：**红 4/7、紫 3/3、蓝 3/3**；红色分母包含三局明确失败 `170422/171054/171720`，不含无法归色的局。另有蓝色模型错色 1 局、目标已不存在的紫色 2 局，均标 `unknown` 并单列。蓝色末局是延迟删除判据；第 3 个独立场景尚未回归。**当前最终部署组合尚无三色各三局同版本、独立新场景的证据，不能宣称已“稳定成功”。** 这里的比率只覆盖列出的场景、参数和 2026-10-12 的试验，不可外推到赛事现场。

## 部署盘点与对照

初始源码/二进制 MD5、实际 BT 参数链和 PR #2 差异见 [`deployed_manifest_20261012.md`](../hit_balloon_v2/deployed_manifest_20261012.md)。用户给出的提交 `1e86aaa4f94e6e6c95d67e538884ff7cb8f56c39` 在本地 `main`，但服务器没有该提交交接文档所述的 2026-10-11 备份或原始试验目录。故“PR #2 红球操作员目视击破一次、紫球 0/4”的数字**无法用本实例重放验证**，也没有纳入以下客观分母。此服务器初始 `visual_servo.cpp` 是负号偏航、无冲刺居中门控的旧源码；原始 `SPRINT!` 格式并无交接所述的占位符错位。安全恢复 `mavros_cnt.cpp/.h` MD5 与交接相符，未修改。

2026-10-06 有 14 局正式记录：4 局“完整成功”仅是冲刺完成，未保存 Actor 快照，客观击破率未知；其余 10 局击球阶段失败。逐局互斥分类见 [`historical_failure_classification_20261006.tsv`](../hit_balloon_v2/historical_failure_classification_20261006.tsv)：A 未检出 3（红 2、紫 1），B 检出后丢失 1（蓝 1），E 击球窗口越界 6（红 6）。9/10 没有目标像素；6 局红 E 类均在无红像素的持续搜索中于 24.6–46.0 s 首次触发安全恢复，故越界是后续现象，不足以解释最初未检出。蓝 B 类仅有 5 次有效像素，横坐标 509–632，未进入接近。完整原始资料在服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/<试验目录>/*telemetry.jsonl`、`observer.out` 与 `results/baseline_runs.csv`。

## 偏航方向：固定输入测量

在正式红局 `20261012T175348_red_A0` 用 `patch_yaw_probe.py` 临时开启一次探针，首次看见红球后悬停，先给 `−0.2 rad/s` 约 2 s，再给 `+0.2 rad/s` 约 2 s。原始逐帧记录为 [`20261012T1753_yaw_probe.log`](../hit_balloon_v2/evidence/20261012T1753_yaw_probe.log)。避开切换瞬态后：负相位 `t=0.506–1.925 s`，球心 `x=400→247 px`，最小二乘斜率约 `−105.5 px/s`，实测机体 yaw 斜率约 `−0.242 rad/s`；正相位 `t=2.532–3.849 s`，球心 `x=216→300 px`，斜率约 `+64.8 px/s`，yaw 斜率约 `+0.204 rad/s`。因此 `err_x>0` 时，当前场景需要**负** yaw 指令；现部署 `yaw_rate=−(kp·err+kd·d_err)` 的符号与此一致。气球所在机器人也在运动，斜率不宜当作精确控制增益。PR #2 所记“紫球误差 −218 px、命令 +0.500 rad/s”在本机方向关系下是向中心纠偏，不能据此把旧负号改正号。探针已从源码恢复，ROS 参数关闭；备份 `/home/ubuntu/yaw_probe_backup_20261012T1752/restore.sh`。

## 取证程序与反例

[`run_with_scene_snapshots.sh`](../hit_balloon_v2/tools/run_with_scene_snapshots.sh) 包装**未改的** `run_formal_trial.sh`：正式试验走共享锁并写 CSV，试验前、结束即刻、结束后 125 s 各取 Unreal `obj list class=BP_Balloon_C`。原始快照与判读 JSON 留在每局正式目录；仓库 [`evidence/README.md`](../hit_balloon_v2/evidence/README.md) 按局索引拷回的快照、图片和判读。无人机未解锁的空白对照 `20261012T1747_idle_control`，同一 UE 进程 268.6 s 内 Actor 3→3→3。它支持短时不会自然消失，但仅有一组对照。

判读器曾有两次误判风险，均保留旧结果供审计：初版把“任意 Actor 少一个”算作请求色；v2 又把 Actor ID 排序当成跨 UE 实例稳定颜色。新场景 PID 210064 中最低编号 `...1415` 的真实相机照片是**蓝球**，同刻分类日志 `blue=1460, purple=0`，直接推翻“最低编号=紫”的跨场景规则。v3 仅使用 UE PID、完整名单及该实例的相机/目标序列映射；未校准、BT 目标错色、多个 Actor 同局删除均返回 `unknown`。`20261012T171720_red_A0` 红球居中冲刺，但真实画面中红球变小、蓝球进入，125 s 后删除的是同场景蓝球，红球仍在，正式判 `false`。它是“冲刺完成≠指定色击破”的直接反例。

取证局的一个重要延迟反例是 `20261012T185145_blue_A0`：同场景只剩真实相机确认的蓝球，正式蓝 BT 有 16 次像素跟踪，结束即刻仍有该 Actor，125 s 后为 0。不能用结束即刻快照直接判失败。该局冲刺前相机可见蓝球，冲刺画面却为蓝墙，颜色日志在 1 s 内从 `blue=1149` 跳到 `34940`，VisualServo 面积从 3.0% 跳到 37.7%/59.4%。这说明墙面大框误检仍存在；Actor 的精确消失时刻和碰撞机理没有事件日志。

## 控制改动与逐步回归

所有 C++ 修改均先保存原文件及 MD5，`catkin_make --pkg mission_pkg -j2` 后重启任务节点、检查进程实际载入插件；Python 无需编译。launch 只做字节级定位替换，保留 CRLF、`optimization/*`、`safety/*`。补丁脚本在 [`patches/`](../hit_balloon_v2/patches/)，版本链和各备份目录见部署清单。

| 改动 | 前→后 MD5（源码或 launch） | 直接观测与局限 |
|---|---|---|
| 冲刺起终点/真实速度/偏差日志 | C++ `a97f5af2`→`0422136d` | `151810` 冲刺实测位移 1.264 m，不能以 1.5×1.2 m 推断碰撞 |
| 对齐容差匹配控制死区 | C++ `0422136d`→`4d9a9909` | `153554` 在 x≈−7,y≈+5 px 时控制输出 0 而 `stable=0`；后续版本消除此不可达区，但单独成功率未验证 |
| 红区入场 yaw 1.5708→3.14159 | launch `a1f0cfc6`→`985fd762` | 旧朝向视觉起点拍到墙，改后 `162215` 首次红跟踪延迟约 0.020 s，Actor 3→2 |
| 红区先高空接近、终点降至 z=1.0 | launch `985fd762`→`9088ac75`→`3fdc18d0` | 全程 z=1.5 的 `165314` 无红像素；终点降回 1.0。一次红任务删除两球的 `163949` 促成航路调整，仍不能证明误碰已消除 |
| 冲刺需居中；近距偏心悬停、丢目标重搜 | C++ `4d9a9909`→`74802b9d`→`b09abd4b` | `170422` 误差 `(126,126)` 冲刺、Actor 不变；`171054` 门控挡住偏心，但前推/假 SUCCESS，仍不变 |
| 红球朝向门控及移除“冲刺前丢失即成功” | C++ `b09abd4b`→`418ae912`，另改 header/`bt_ros.cpp` | 同场景 `171720` 红任务错删蓝球；`173621` 门控阻止偏航过大时冲刺，红面积峰值 38.5%，红 Actor 删除，降落成功，但整局 `mission_success=false` |
| 丢目标时世界坐标位置保持 + 原地 yaw 搜索 | C++ `418ae912`→`e440050e`，header `1093026e`→`d3324b04` | `181001` 旧零机体系速度使搜索位置漂移约 2.5 m；`181709` 新版搜索位置在 `(5.17,−1.93)` 附近，未见击球期越界；两局紫 Actor 在此前已消失，不能算紫球击破对照 |
| 模型颜色一致性校验、最多重试一次 | `/home/ubuntu/model/mission_once.py` `dcc050dd`→`4b0ae381` | `184356` 蓝任务被模型错写为紫，BT `purple_balloon`，判 `unknown`；补丁静态测试错误色拒发/正确色通过，下一局 `185145` 模型首答蓝且 BT 正确。尚未实测“首次错色后重试成功”频率 |

固定偏航探针在上述控制版本中属于**临时诊断变量**；它已回滚，不能把探针局当作当前版本的同版本重复试验。紫色前进速度 0.35 的两局尝试 `181001/181709` 均在紫球已经不存在的场景，不能得出速度效果；当前 launch 仍为 `forward_velocity=1.0`，可在真实失败复现后单变量再测。

### 有颜色校准的正式回归

以下路径均以服务器 `/home/ubuntu/tcei_baseline_tools/results/formal_trials/` 为根。`3→2→1` 是本局的试验前→结束即刻→125 s 后 Actor 数；`true/false` 是代理判读，非裁判分数。逐局原始文件：`scene_snapshots.jsonl`、`judgement.json`、`*telemetry.jsonl`、`mission_once.out`、`observer.out`。其他 `unknown` 局在证据索引中逐条保留。

| 目录 | 色 | Actor 变化 | v3 判读 | 关键反例或限制 |
|---|---|---|---|---|
| `20261012T162215_red_A0` | 红 | 3→3→2 | true | 红 yaw 改动后的首次跟踪 0.020 s |
| `20261012T162655_purple_A0` | 紫 | 2→1→1 | true | 与上一局同 UE；紫目标跟踪、单球删除 |
| `20261012T163138_blue_A0` | 蓝 | 1→0→0 | true | 同 UE 最后一球；UE 的 `0 Objects` 解析修复并无插入任务地回补 |
| `20261012T170422_red_A0` | 红 | 3→3→3 | false | 面积门控前偏心 `(126,126)` 冲刺 |
| `20261012T171054_red_A0` | 红 | 3→3→3 | false | 居中门控挡住冲刺，后续前推丢目标 |
| `20261012T171720_red_A0` | 红 | 3→3→2 | false | 删的是蓝球；红球留下，旧判读误报已更正 |
| `20261012T173621_red_A0` | 红 | 2→1→1 | true | 红球删除，但全局任务失败，降落成功 |
| `20261012T175348_red_A0` | 红 | 3→3→2 | true | 临时 ±0.2 yaw 探针局，全局成功 |
| `20261012T180225_purple_A0` | 紫 | 2→1→1 | true | 紫面积峰值 46.7%；全局失败，降落成功 |
| `20261012T182513_blue_A0` | 蓝 | 1→0→0 | true | 同 UE 最后一球；全局成功 |
| `20261012T183325_red_A0` | 红 | 3→2→2 | true | 最终控制版；无冲刺，observer 全局失败 |
| `20261012T183848_purple_A0` | 紫 | 2→1→1 | true | 最终控制版；冲刺面积 14.36%→54.07%，全局成功 |
| `20261012T184356_blue_A0` | 蓝 | 1→1→1 | unknown | LLM 把蓝写成紫；属于模型语义输出异常 |
| `20261012T185145_blue_A0` | 蓝 | 1→1→0 | true | 加颜色校验后正确蓝 BT；延迟删球、墙面误检同时存在 |

按颜色的可比口径：红球在 `170422/171054/171720` 三个逐步补丁版本中 **0/3**，在后续 `173621/175348/183325` 三个版本中 **3/3**；版本、场景和剩余气球集合同时变化，**不能**把 0→3/3 全部归因于任一单独补丁。紫球三组已校准局 **3/3**，蓝球三组已校准局 **3/3**，但均跨增量版本。PR #2 紫球 0/4 是操作员记录且服务器原件缺失，不与代理判据相加。最早数局以及多球同局消失、无校准/无目标的样本均为 `unknown`，不能从分母中悄悄当成功。

## ArUco 与安全结果

已审阅 `180225`、`181001`、`181709`、`182513`、`183325`、`183848`、`184356`、`185145` 八局的真实遥测：二维码检测窗口均在 **0.036–0.149 s** 内由 ENABLED 到 DISABLED，结束日志每局回调数 **1 或 2**、`decode_fail=0`，均识别成功，观察到 **0 次停摆**。这些窗口均短于 1 s，故没有 `callbacks/s=` 每秒计数行；“没有 0/s 行”**不能**当作对长窗口回调停摆假设的证伪。工具 [`summarize_aruco.py`](../hit_balloon_v2/tools/summarize_aruco.py) 可从每局原始 telemetry 复算窗口、回调数和 0/s 次数。此前 10-06 正式批次 ArUco 13/13 通过，与本次短窗口观察一致，但同样不能证明偶发问题彻底消失。

明确反例：`173621` 红、`180225` 紫、`183325` 红虽有目标 Actor 删除，但全局 `mission_success=false`；三局 observer 均显示最终降落成功（以各局 `observer.out`/CSV 为准）。`170422/171054/171720` 三局红明确未中；其中 `171720` 是误删蓝球。新位置保持前的 `181001` 紫局在目标已不存在的场景搜索漂移并触发安全恢复，后续 `181709` 在相同剩余场景未再出现同等搜索漂移。`ForceSuccess` 仍可能掩盖击球失败，需由场景判据独立审核。

## 回滚与当前限制

在无人机落地、无 `/tmp/tcei_formal_trial.lock` 时执行。以下恢复脚本各自校验 MD5；C++ 恢复后需 `catkin_make --pkg mission_pkg -j2` 并重启 `/llm_mission_node`。若要一次退回本次工作之前，应按**下面顺序**逐层恢复，而非只运行某个中间备份。

```bash
bash /home/ubuntu/search_position_hold_backup_20261012T1816/restore.sh
bash /home/ubuntu/red_heading_guard_backup_20261012T1735/restore.sh
bash /home/ubuntu/close_align_reacquire_backup_20261012T1715/restore.sh
bash /home/ubuntu/sprint_center_gate_backup_20261012T1709/restore.sh
bash /home/ubuntu/red_final_descent_backup_20261012T1700/restore.sh
bash /home/ubuntu/red_staging_height_backup_20261012T1650/restore.sh
bash /home/ubuntu/red_entry_yaw_pi_backup_20261012T1618/restore.sh
bash /home/ubuntu/visual_alignment_deadzone_backup_20261012T1539/restore.sh
bash /home/ubuntu/sprint_observability_backup_20261012T1529/restore.sh
bash /home/ubuntu/mission_color_guard_backup_20261012T1850/restore.sh
```

2026-10-12 18:58 左右在启动下一个独立场景后，SSH 端口 `120.209.70.195:30316` 拒绝连接；独立 TCP `connect_ex` 返回 Windows `10061`。按仓库 `AGENTS.md`，需 gpufree.cn 控制台恢复实例。已请求项目负责人协助；因此报告目前不含该新场景的正式回归结果、启动状态或其安全检查。上述三色样本数已经达到各三局，但**最后的稳定性复核仍未完成**。
