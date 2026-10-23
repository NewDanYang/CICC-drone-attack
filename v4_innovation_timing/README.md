# 第四部分：创新节点文档 + 用时优化（2026-10-19 起草）

依据 `docs/next-phase-plan-v2.md` 第三、四部分，在 Part 1（气球阶段）按新五项
标准封存（见 `v3_stability/reports/hit_balloon_part1_final/REPORT.md`）后开始。

## 目录归属提醒（写在最前面，必须先确认）

按 `AGENTS.md` §9 的团队分工表，`v2_time_optimization/`、`v2_1_ego_velocity/`
以及"新建的多模态/规划目录"都归**评分优化方向**所有，这个方向同时负责多模态加分
（第三部分）和创新路径规划/用时（第四部分）——也就是说第四部分名义上和正在做
第二、三部分的可能是**同一个人**。

本目录下的内容是**草稿**，没有写进 `v2_time_optimization/`，就是为了不在对方
不知情的情况下动他们的目录。`v2_time_optimization/`、`v2_1_ego_velocity/` 最后
一次提交的时间看不出近期有人在用（git log 查不到最近活动），但这不代表没有人
在本地进行、还没推送。**合并或采信本目录内容前，请先和负责评分优化方向的人核对**，
避免两边各做一份、互相冲突。

## 本目录内容

| 文件 | 对应 next-phase-plan-v2.md 条目 | 状态 |
|---|---|---|
| [`innovation_nodes_draft.md`](innovation_nodes_draft.md) | 4.1 创新程序节点技术文档 | 草稿，基于已冻结代码和既有试验数据，**没有现场复核 MD5**，比赛前必须重新核对 |
| [`path_planning_proposal.md`](path_planning_proposal.md) | 4.2 创新路径规划方案 | 仅方案评审稿，**未动代码**，按规则要求"先写方案、方案评审通过后再排期" |
| [`timing_baseline.md`](timing_baseline.md) | 4.3 用时基线 | 基于已有 24 组历史试验日志的离线分析，**不是针对当前封存版本的新计时**，见文内局限说明 |
| `evidence/stage_timing.py` | — | 4.3 用的离线分析脚本，纯只读，解析本地已保留的 `rosout_events.jsonl` |
| `evidence/stage_timing_output.txt` | — | 脚本的完整原始输出 |

## 没有做的事

- 没有在服务器上跑任何新试验，没有改任何线上代码。
- 没有对任何"创新节点"做比赛要求的"比官方代码更快/更平稳/肉眼可见优势"的
  对照实验——`innovation_nodes_draft.md` 里列的候选数据都是各节点**各自修复时**
  产出的对照数据（修复前 vs 修复后），不是和"官方未修改 demo"的直接对比，
  这两者按规则条文看可能是同一件事，但也可能被裁判认为不够——需要有人在
  比赛前额外补一组"官方 demo 原始代码 vs 当前封存代码"的直接对照，这是
  本草稿最大的缺口，已经在 `innovation_nodes_draft.md` 里单独标出。
