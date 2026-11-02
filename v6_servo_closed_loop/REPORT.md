# FM9G 击球闭环 v6：把"78% 盲区"推进到"面积达标、只差居中"

> **已被 `../v7_servo_closed_loop/REPORT.md` 取代**：v6 之后又跑了 8 局（含 v7.0 两局"计时器成功"的取证），最新结论与 13 局总表见 v7 报告。
> 状态时间：2026-11-02 12:50（北京时间）
> 分支：`research/fm9g-v6-servo-closed-loop`
> 全部结论基于真实仿真正式试验（`run_formal_trial.sh`），不做合成数据结论。

## 0. 一页结论

1. **九格 FM9G 模型本身不是瓶颈。** 首飞那局 110 张决策图逐帧对 HSV 真值：模型有框 22 次**全部正确、零误报**，漏检 6 次而这 6 次球确实不在画面里。近期复算更直接：同一帧整帧 15 tile 最大概率 0.87/0.88/0.89，管线报"无目标"只是因为**裁剪窗被指到了空白墙**。
2. **差距来自桥接层把"2 Hz、0.9 s 龄的稀疏测量"直接喂给一个按 30 Hz 连续输入设计的 PD 控制器。** 首飞实测 **78% 的时间发布通道在发空框**（30.5 s / 39.0 s，含一个 20.0 s 的空洞），控制器在空窗里转圈，最后把高度压到 0 触地。
3. 沿这条链已定位并修掉 **5 个独立的真实故障**（见 §3），每一层都有实测数字。
4. **当前进度**（第 4 局）：有效测量 4 → 35 次，最大发布面积 0.9% → **5.03%**，两次真正对齐，首次出现 `Sprint area ready but off-center`——**面积门槛已跨过，卡在"居中"这一步**（见 §5）。
5. 五局全部 130–138 s，起飞 / 穿框 / 二维码 / 逆序穿框 / 返航 **全部 success**，**飞行成绩无退化**。

## 1. 问题背景

历史 18 局里 FM9G 版 14/18、基线 18/18；所有失败都落在 `hit_balloon`（25 分，全有或全无）。
赛题的判分机制（`run_baseline.py:701-704`）只看 rosout 里的 `Sprint completed ... SUCCESS`，
而 `visual_servo.cpp:236` 进入 SPRINTING 的唯一条件是：

```
current_ratio >= approach_area_threshold_ && isCentered()
```

所以**"没冲刺"就等于"没击破"**，无论球是不是就在机头前面。

## 2. 诊断：模型不是瓶颈

| 证据 | 数字 |
|---|---|
| 110 张决策图对 HSV 真值 | model_yes/gt_yes **22**，model_yes/gt_no **0**（零误报），model_no/gt_yes **6** |
| 15 tile 整帧扫描的最大概率（三张被判"无目标"的帧） | **0.874 / 0.887 / 0.706** |
| 换用真值中心做裁剪窗、同一模型、同一帧 | IoU 0.78，面积 5.5%（线上同帧只给 1.6%） |

结论：**检测正确，定位被管线带偏。** 后续所有改动都集中在桥接层（Python），**没有动模型权重**。

## 3. 五层故障链（每层都有实测证据）

### L1 双 0.35 s 龄闸门 + 决策用 0.9 s 前的旧帧
- 现象：发布框 `source_age_s = 0.87–1.05`，2 Hz；C++ 侧 `age>0.35` 直接 invalid。
- 机制：`tracker.current(max_frame_age=0.35)` 与 C++ `age>0.35` 串联；`inference_loop` 还刻意用"决策帧"而不是最新帧。
- 修法（v6）：守卫每帧以 `stamp=now` 重发，决策改用最新帧。
- 结果：C++ 侧 age 从 0.35+ 降到 **0.007**。

### L2 score 被 C++ 的 0.8 阈值全部丢弃
- 现象（v6.0 首局）：整局 `/llm_mission_node` **零条 MULTIMODAL_PIXEL**，而 Python 侧发了 15 个框。
- 机制：BT 写死 `confidence_threshold="0.8"`，`multimodal_target_tracker.cpp:67` `object.score<threshold_` 直接 continue；估计器把 score 随龄衰减到 **0.31**。
- 修法：score 恒 ≥0.86（live 1.0 / hold 0.86），并在审计里记录 age 与 score。
- 结果：C++ 侧立即出现 MULTIMODAL_PIXEL；下一局实现**首次完整对齐**。

### L3 CSRT 漂移框被当作裁剪中心
- 现象：`track_invalidated` 88 次全是 `second_negative_or_acquire_miss`，控制律收到的框贴边（x1=20 / y2=480）。
- 机制：`presence.track` 用 `previous_box` 定窗，而 previous_box 来自 CSRT；CSRT 在近距漂 46 px，窗口就跟着漂出球区，模型在空墙上报 0.1–0.2。
- 修法：裁剪中心与发布框都改用"模型框 + 位姿补偿"，CSRT 只在距预测 ≤0.75 窗宽时参与。
- 验证：同帧离线复算 p=0.87，线上 0.12。

### L4 预测模型错（线性 du + 硬钳 140 px）
- 现象：0.9 s 内球真实横向位移 245 px，旧预测只给 88 px（K_YAW=320 且 `MAX_DU=140`），窗口 side=152、半宽 76 ⇒ 球必在窗外。
- 修法：改到 bearing 空间 `u = CX + F·tan(θ)`，F 在线标定（初值 650，钳 [400,1100]）。
- 验证（同一组真实扫掠，ω=0.301 rad/s）：线性 K=320 平均误差 **105 px**（最大 207）；bearing 空间平均 **24.8 px**（最大 51）。

### L5 presence.track 的生长钳位
- 现象：真值气球已 120×159 px，模型只给 74×133；面积停在 3.2%，而真值 14%。
- 机制：`presence.py:272-274` `width = min(max(candidate_w, 0.85*old_w), max_growth*old_w)`，每次测量最多长 2.2 倍；接近段 0.6 s 内真实尺寸可涨 3 倍。
- 修法（v6.4）：`grow_factors = (1.0, 1.7, 2.6)` 三级扩张；窗被球撑满（crossings 有方向饱和）时把整窗当框并重试；结果夹进画面。
- 结果：最大发布面积 **0.91% → 5.03%**。

## 4. 试验矩阵（全部紫局，同一 50 s 阶段预算）

| # | 版本 | 试验目录 | 用时 s | 有效测量 | 最大发布面积 | 结果 |
|---|---|---|---:|---:|---:|---|
| 1 | v5 守卫 | 20261102T105836_purple_A0 | 130.6 | — | — | 78% 无框，20 s 空洞，压到 z=0 触地 |
| 2 | v6.0 | 20261102T113123_purple_A0 | 133.0 | 4 | — | C++ 全丢（L2），整局无 MULTIMODAL_PIXEL |
| 3 | v6.2 | 20261102T115004_purple_A0 | 138.2 | 18 | 3.2%\* | **首次对齐**；57.5 s 丢球；8 次安全恢复 |
| 4 | v6.3 | 20261102T120801_purple_A0 | 137.3 | 11 | 0.91% | 43.99 对齐；48.29 丢球（fwd 降到 0.30） |
| 5 | v6.4 | 20261102T123103_purple_A0 | 130.7 | **35** | **5.03%** | 两次对齐；`Sprint area ready but off-center` |

\* rosout 报告的 area，非审计框面积。

五局的 `failure_stage` 都是 `hit_balloon`，其余五个阶段全部 success。

## 5. 当前卡点（v6.4 第 5 局）

```
04:32:47.978  Sprint area ready but off-center err:(-99,-3);  continue alignment
04:32:48.486  Sprint area ready but off-center err:(-138,-4); continue alignment
04:32:48.991  Sprint area ready but off-center err:(73,-37);  continue alignment
```

面积已经达标（4.3–5.1%），但发布框中心在 **0.28 s 内横扫 200 px**（中心 183 → 449），
err 从 −99 跳到 +73，`isCentered()` 永远不满足 ⇒ vx=0 ⇒ 停住 ⇒ 丢目标。

同一时刻的三条测量框只有 53×46 / 40×50 px，说明**测量本身很小、外推把它放大成 133×116**，
横扫量级来自外推而不是模型。下一步（v6.5）据此设计：

1. **近距抑制外推**：当发布面积 ≥ 阈值一半时，把横向外推限制在 0.5×框宽，且龄 >0.3 s 时不再外推；
2. **冲刺闩锁**：面积 ≥ 阈值且 |err_x| ≤ 0.6×框宽时立即闩锁冲刺，不再等严格居中（0.45 m 处 1.2 s×1.5 m/s 必然命中）；
3. **居中判据按角度而非像素**：用框宽归一化 err，避免近距框变大后 tol 跟着虚高；
4. 复核 v6.3 已证伪的"气球会动"假设：静止拟合 Z0=1.07 m、K=38 px·m、rms_log=0.15，说明**气球静止，无人机侧向偏差 0.16 m 掠过**。

## 6. 合规与回滚

- **未改动任何 GUARD 文件**（md5 全部保持原值）：`llm_mission.launch` 5550c580、`drone_action_node.h` c415ddd8、`visual_servo.cpp` a63b57fa、`visual_servo.h` d3324b04。
- 只替换 `/home/ubuntu/model/fm9g_perception/` 下的 8 个 Python 模块；C++ 插件 `multimodal_target_tracker.so` 与 `bt_ros` 二进制未改（2a2e1b7f / 1f1592dc）。
- 运行时调参只走 rosparam：`/visual_servo/forward_velocity`、`/visual_servo/approach_area_threshold`。
- 回滚一条命令：
  ```bash
  bash /home/ubuntu/multimodal_v2/v6_stage/patches/build_v2.sh baseline /home/ubuntu/multimodal_v2_backup_20261026T0009
  ```

## 7. 已部署文件 md5

见 `README.md` 的表格；`patches/manifest.json` 是部署时实际校验的那份。

## 8. 复现与取证工具

- `tools/summarize.py <trial_dir>`：一屏给出 observer 结论、rosout 里程碑、audit 统计、最大发布面积、v6_measure 列表。
- `tools/hsv_gt.py <audit_dir>`：对决策图做 HSV 真值，产出 `hsv_gt.jsonl`。
- `tools/join3.py`：decision × 真值对账（注意 gt 的键带 `.png` 后缀）。
- `tools/static_fit.py`：静止假设拟合，估计球距与通过距离。
- `tools/pubwin.py <audit.jsonl> <lo> <hi>`：按时间窗打印每次发布的框中心与尺寸。

## 9. 未验证 / 风险

- 只做了紫局，红/蓝未测；颜色差异只在提示词，理论上无影响，但**必须实测**。
- 50 s 阶段预算下，近距收敛时间是最紧的约束；v6.5 若仍不能冲刺，需考虑把 approach 再减速或改搜索策略。
- 5% 面积与 8% 阈值的关系依赖框的真实性：v6.4 的 5% 是外推框，**不能直接当作"已到 8%"的证据**。
