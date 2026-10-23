# 规则合规候选 v2：真实模型新措辞验证（2026-10-15）

**结论：验证 B 过门槛，可进入合并评估；仍有明确反例。** 本轮重新部署与上一轮字节相同的四文件候选，真实模型调用线上 `mission_once.py`，探针不向 `/mission_command` 发布。没有重测窗口性能。部署时旧版 MD5 与预期一致；[完整部署输出](deploy_log.txt)记录了逐文件新旧 MD5 和备份目录 `/home/ubuntu/rule_compliance_backup_20261015T144606/`。模型 MD5 为 `1597c5c139632fff4823e8b4d7cadd28`，提示词 MD5 为 `204b91245046f3d11ac342a5b229cc20`。

| 专项措辞 | 2026-10-14 旧候选 | 本轮 v2，每类 5 次 |
|---|---:|---:|
| `blue_ball` | 0/3 | **5/5** |
| `red_yanse` | 0/3 | **5/5** |
| `distractor_color` | 0/3 | **4/5** |
| `step_land` | 0/3 | **5/5** |

专项合计 **19/20 = 95%**；前三个颜色相关旧样本合计 0/9，降落旧样本 0/3。唯一反例是 `distractor_color` 第 1 次：模型依次给出 `detect_aruco; land`、五步含红球、三步含红球，`single_action_problems()` 三次均判定多余步骤并触发重试；用尽重试后兜底原样选了**不含击球的** `detect_aruco; land`。这是步骤缺失的实际风险，不能算作命中目标。三次原始回答和完整 `[命令校验]` 日志见[专项 JSONL](llm_paraphrase/targeted/samples.jsonl)，逐类计数见[专项 CSV](llm_paraphrase/targeted/cases.csv)。

全部 20 类每类 3 次，排除 2 类无颜色区域指令的 6 次后，严格准确率 **52/54 = 96.3%**，超过 ≥95%、≥40 次门槛；上一轮为 **31/54 = 57.4%**。判据仍要求准确顺序、合法命令、正确颜色及带 `command` 标签的代码块。上一轮错误类型为 `no_command_block` 9、`steps_missing_or_extra` 14；本轮分别为 **2、0**，未出现新的错误类型。两次失败分别是 `step_takeoff` 与 `step_cross`：回答步骤正确，却用了无语言标签的代码块，线上校验未重试，严格判据照常记错。无颜色区域 6 次仍为设计未决，未混入分母。[全量 JSONL](llm_paraphrase/full/samples.jsonl)、[逐类 CSV](llm_paraphrase/full/cases.csv)、[总体指标](llm_paraphrase/full/overall.json)保留原始证据。含重试的单次调用耗时 P50/P95 从 **2.894/6.155 s** 到 **2.956/6.573 s**。

[探针用例核对](probe_case_filter_check.txt)确认不带筛选参数仍是与上一轮同序的 20 类；专项筛选为 4 类。离线桩测试复跑为 [25 PASS、0 失败](offline_fallback_test.txt)和 [6 PASS、0 失败](offline_display_test.txt)。这些桩测试只验证控制逻辑，不替代上述真实模型样本。

可选端到端冒烟三色各一局，严格串行、A0、同一场景，三局均发布对应颜色的六步命令；起飞、穿框、识码、逆穿、降落均 **3/3** 成功。击球 observer 仅蓝色标为成功，红和紫均为**未观测**，所以整局成功 **1/3**；蓝色还记录 1 次边界触发。ArUco 各局 `callbacks=1`、解码失败 0，窗口时间只作为局内诊断，不用于重判窗口候选。逐局目录、阶段、回调及时间见[冒烟 CSV](smoke_trials/formal_trials.csv)，各局 runner、observer 和模型输出见 [`smoke_trials/`](smoke_trials/)；完整原始日志与遥测的[服务器路径](smoke_trials/source_paths.txt)已记录。冒烟样本量仅三局，不能证明三色击球稳定成功。

**处理决定：保留候选部署，提交草稿 PR 进入合并评估。** 审查时重点看否定颜色句在兜底时可能漏掉击球，以及无 `command` 标签回答仍被发布。没有修改比赛规则、安全边界或验证判据。冒烟后在 `armed: False` 时重启到新场景，[重启日志](smoke_trials/post_smoke_reset.log)显示 `environment_started=1`；正式锁不存在，模型交互进程已重新运行，四文件 MD5 仍为候选值。需要回滚时，在确认无正式试验、飞控未解锁后执行 `bash /home/ubuntu/rule_compliance_backup_20261015T144606/restore.sh`，再重启仿真环境；该脚本恢复四个旧版 MD5。结论仅适用于本轮线上模型、20 类提示词、每类 3–5 次采样；端到端结果仅适用于这三局 A0 冒烟，不能外推到正式比赛成功率。
