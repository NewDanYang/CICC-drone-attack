# CICC 无人机搜索打击项目

这是我们参加具身智能无人机搜索打击赛题的代码和实验记录。

简单说：让无人机读懂自然语言任务，在仿真场地里起飞、穿过方框、识别二维码、返回穿框、寻找并击打指定颜色的气球，最后返航降落。我们用的是 **ROS、PX4、MAVROS、RflySim、Ego-Planner，以及视觉识别和行为树**。

这个仓库不只是最终代码，还保留了失败实验、分析报告和回滚方法。**仓库代码不会自动部署到服务器**；服务器真正运行的是 `/home/ubuntu/catkin_ws/`，每次测试前都要核对实际源码和参数。

## 现在做到哪一步了？

| 方向 | 当前情况 |
| --- | --- |
| 基础任务链 | 自然语言 → 动态行为树 → 飞行控制的全流程已经跑通 |
| 起飞、穿框、返航和降落 | 已有多轮正式仿真成功记录，仍需整套版本的回归 |
| 二维码识别 | 目前成功率表现不错；历史偶发的回调停摆没有被彻底定因 |
| 安全边界恢复 | 修复了恢复目标和确认门限重合造成的死锁，已做真实越界测试 |
| 三色气球 | 同一控制版本、三个 UE 场景中，红紫蓝各有 3/3 的 **Actor 删除代理判据**；这不是官方裁判击破回执 |
| 击球过程 | 还有墙面误检、边界恢复频繁、任务 SUCCESS 与气球是否真的破裂不一致的问题 |
| 时间优化 | 起飞重试间隔缩短方案有正式数据；Ego-Planner 0.40 m/s 虽提升第一次穿框速度，但已回滚到 0.35 m/s |
| 创新路径规划 | 非目标气球避让代价做过概念验证，但用了 UE 真值桥接，不能当作已完成的比赛加分功能；独立规划器方向也还没有形成经验证的优势 |
| 九格多模态 | 离线识别评测在进行，尚未完成视觉结果参与控制的正式验收 |

**不要只看日志里的 `mission_success=true` 就认为球被击破。** 行为树和 observer 的成功语义曾与真实气球状态不一致。三色判读报告通过同场景 Actor 清单、相机日志等给出了更强的证据，但仍然不是赛事官方判分。

## 从哪里开始看？

不必一上来翻整个 ROS 源码，推荐按下面顺序：

1. **[赛题原文](打击.pdf)**：先弄清比赛到底要求什么、哪些会扣分。
2. **[项目协作说明](AGENTS.md)**：服务器怎么用、实验怎么留证据、哪些错误结论已经被排除。注意其中一些“当前重点”是早期快照，最新状态以下面的报告为准。
3. **[三色击球 V2 报告](v3_stability/reports/hit_balloon_fix_20261012.md)**：视觉伺服、颜色纠错、代理击破判据及尚存的问题。
4. **[ArUco 稳定性报告](v3_stability/reports/aruco_fix_20261006.md)**：识别参数对比，以及历史停摆还不能归因的原因。
5. **[时间优化报告](v4_innovation_timing/time_optimization/REPORT.md)**：起飞重试、稳定等待、速度档位的对照与回滚。
6. **[气球避让代价实验](v4_innovation_timing/path_planning_experiment/REPORT.md)**：做了什么、为什么暂时止损。
7. **[独立规划器实验与交接](docs/astra-handoff-path-planning-direction-b.md)**：另一条规划路线的设计思路；PR #6 合入的是这份交接文档，不能据此宣称独立规划器已经在主分支完成验证。

## 仓库目录是干什么的？

| 目录 | 内容 |
| --- | --- |
| `official_baseline/` | 官方原始工作空间快照，用来对照，不要直接当成当前比赛版本 |
| `baseline_tools/` | 启动仿真、执行正式任务、记录日志和分析数据 |
| `v1_safety_recovery/` | 安全边界恢复及修复历史 |
| `v2_time_optimization/` | 早期用时分析和优化实验 |
| `v2_1_ego_velocity/` | Ego-Planner 速度档位测试 |
| `v3_stability/` | ArUco、气球视觉控制、部署快照、回滚脚本和证据 |
| `v4_innovation_timing/` | PR #4 时间优化与 PR #5 路径规划概念验证 |
| `docs/` | 协作交接、规则与方案说明 |
| `打击.pdf` | 比赛规则原文 |

在 `v3_stability/hit_balloon_v2/` 中还能找到运行过的源码快照、补丁、场景判读工具及证据图片。**实验文件已合并进 Git，并不意味着实验性算法已经部署或建议作为参赛版本启用。**

## 怎么运行一次测试？

下面的命令在 **仿真服务器** 上运行，而不是直接在自己的 Windows 电脑上运行。

先加载 ROS 工作空间：

```bash
source /opt/ros/noetic/setup.bash
source /home/ubuntu/catkin_ws/devel/setup.bash
```

在服务器重启或完整重置后，启动一次共享环境：

```bash
export DISPLAY=:20
export XAUTHORITY=/home/ubuntu/.Xauthority
cd /home/ubuntu/tcei_baseline_tools
bash ./start_sim_environment.sh
```

环境已经就绪后，另开终端运行一局正式任务：

```bash
cd /home/ubuntu/tcei_baseline_tools
bash ./run_formal_trial.sh red
```

把 `red` 换成 `purple` 或 `blue` 即可。**不要每跑一局就重新启动整套仿真**，也不要在其他队友正在跑测试时清除任务锁。

结果通常保存在：

```text
/home/ubuntu/tcei_baseline_tools/results/formal_trials/
/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv
```

部分历史试验已迁移到服务器数据盘，具体位置以对应实验报告为准。详细 SSH 用法、进程锁检查、编译命令见 [AGENTS.md](AGENTS.md)。

## 现在真正要做的事

我们已经花了不少时间证明“这套东西能跑”，接下来更重要的是把它做成**可靠、合规、能重现的比赛版本**。

- **统一运行版本**：明确哪些源码、launch 参数和插件是真正经过验证的；把服务器实际部署与 Git 提交对应起来。
- **处理击球可靠性**：降低墙面误检、冲刺偏移和频繁碰边界，区分“飞完任务”和“确实击破指定球”。
- **检查评分要求**：包括视觉反馈控制、九格多模态、显示窗口、预设点等问题；离线补丁不算上机通过。
- **继续多模态和路径规划实验**：有效才进入参赛版本；不如官方或依赖仿真真值的方案就保留为研究记录。

## 我们怎么管理改动？

每人单独开分支，实验有结果后发 PR；不要直接把试验版覆盖到稳定运行代码里。改前备份、记录参数和校验值；改后留下原始日志、对照结果以及回滚方式。

对于 PR #4～#6，**合并只是把代码和实验资料收进仓库**：

- [PR #4](https://github.com/NewDanYang/CICC-drone-attack/pull/4)：时间优化，保留有效候选，0.40 m/s 已回滚。
- [PR #5](https://github.com/NewDanYang/CICC-drone-attack/pull/5)：气球避让代价 PoC，服务器已回滚，不作为正式规划加分成果。
- [PR #6](https://github.com/NewDanYang/CICC-drone-attack/pull/6)：规划器替换的交接文档；相关实现和验证状态应以独立实验报告核对。

有疑问优先看对应实验报告和原始日志，不要靠一个绿勾、一次成功或者 README 中的概括判断算法是否真正有效。
