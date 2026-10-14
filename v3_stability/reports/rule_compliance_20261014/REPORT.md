# 规则合规上机验证与模型新措辞测试（2026-10-14）

**结论：候选版已回滚，未通过上机验收。** 三个部署文件的 MD5 与交接值一致，部署脚本完整输出及备份路径见 [`deploy_log.txt`](deploy_log.txt)。仿真重启出现 `environment_started=1`；候选运行时 `/object_detection/visualization/show_window=true`、`/llm_mission_node/debug_display` 未显式设置（采用候选默认 `true`）。红色首局 ArUco 阶段虽成功，ENABLED→DISABLED 却耗时 **0.561 s**，为对照 9 局最大值 **0.217 s** 的 **2.59 倍**。按任务的退化停机条件，在该局落地、正式锁释放后执行 [`rollback_log.txt`](rollback_log.txt) 所记回滚并重启仿真；目前线上三文件 MD5 已恢复为 `4b0ae381… / 0f15e84b… / 9eda7268…`，无正式试验锁。

本地离线测试在收尾时复跑：[`mission_once` 18/18](offline_fallback_test.txt)、[`ArUco` 6/6](offline_display_test.txt)。这些是桩测试，不代替下面的上机结果。

## 现场证据与对照

| 验证项 | 实测 | 限制 |
|---|---|---|
| 两个感知窗口 | [`root_in_flight.png`](windows/root_in_flight.png) 于 **15:12:58 UTC** 显示 ArUco 窗口 `ID: 35`，在识别结束 **15:12:41 UTC** 后持续可见；[`detection_067.png`](windows/detection_067.png) 于 **15:14:01 UTC** 在 `Detection + Color` 窗口显示绿色方框 bbox。窗口标题、逐帧记录见 [`capture_index.txt`](windows/capture_index.txt)。 | 只证明红局的画面与窗口可见性，未证明每个阶段都持续显示 |
| 正式红局 | 目录 `20261014T231142_red_A0`，**137.411 s**；起飞、穿框、ArUco、逆穿、降落均 `success`；ArUco **3 回调、0 解码失败、0.561 s**；边界触发 **0**。Actor **3→2**，但新 UE PID 5253 缺逐实例颜色校准，击球代理判据为 `unknown`，observer `mission_success=false`、`hit_balloon_status` 未观察。 | 对照 9 局 ArUco 0.106–0.217 s、1–2 回调、降落 9/9；详细表与原始路径见 [`trials/COMPARISON.md`](trials/COMPARISON.md)。截图采集每 2 s 运行，可能增加延迟，不能将差异单独归因于 GUI 代码 |
| 三色无退化 | **未完成：1/3 局**，紫、蓝未启动。 | 首局窗口时长已触发交接要求的“明显变慢即回滚”；不能宣称三色稳定或不退化 |
| 真实模型发布 | 候选 MD5 `e7bb1627…` 用历史蓝色完整指令首答生成 `hit_balloon:blue`，独立 ROS 主站 `/mission_command` 实收 6 条命令。无 `[命令校验]` 重试行；候选正则对无颜色和双颜色输入均返回 `None`。见 [`isolated_publish/`](llm_paraphrase/isolated_publish/)。 | 独立主站不连接飞控，验证生成与发布，不验证实际飞行；本次首答正确，未在真实模型上触发错误色兜底分支，后者只有 18/18 离线桩测试 |

## 新措辞采样

回滚后以服务器 `/tmp/rule_compliance/mission_once.py` 的**同 MD5 候选副本**调用其 `load_model`、`generate_validated_commands`，模型只加载一次、**未调用 publish**。20 套输入各 3 次，共 **60** 次；6 次只给区域不指定颜色单列为设计无解，不进入准确率分母。严格判据为带 `command` 标签的代码块、合法命令、目标颜色一致、与提示逐步对应且顺序不增删：**31/54 = 57.4%**，低于 95% 门槛。另有 **9** 次命令序列正确但代码块没有 `command` 标签；候选解析器会接受这种无标签代码块，若宽松接受，完整序列也仅 **40/54 = 74.1%**。其余 **14** 次擅自增加或缺少步骤，**0** 次目标错色、**0** 次未知命令。只给 A/B 区的 6 次**全部自行选了红色**，颜色映射无规则依据，须由赛题/提示词另行澄清。全部 60 次生成耗时（含重试）P50 **2.894 s**、P95 **6.155 s**。逐样本原文、最终命令、重试日志、错误分类见 [`samples.jsonl`](llm_paraphrase/samples.jsonl)，分组表见 [`cases.csv`](llm_paraphrase/cases.csv)。

回滚命令：`bash /home/ubuntu/rule_compliance_backup_20261014T230542/restore.sh`，再在无人机解除武装且无正式试验锁时运行 `/home/ubuntu/tcei_hit_balloon_v2_tools/reset_scene_checked.sh` 重启。该回滚**已经执行**，重启回执见 [`rollback_restart.log`](rollback_restart.log)。开始前经团队确认无人占用，清除了一个锁内 PID 全部死亡、修改时间为 10 月 13 日的旧仿真锁。服务器还留有 `/tmp/rule_compliance/` 的候选文件、测试脚本和样本原件；未修改 `safety/*`、比赛规则、launch 或他人的正式数据。以上窗口和飞行结论只涉及 **红色、A0、1 局、UE PID 5253**；模型统计只涉及此模型、这 20 套措辞及本次采样，不外推为赛场正确率。
