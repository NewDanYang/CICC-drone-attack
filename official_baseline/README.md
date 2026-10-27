# 官方基线的版本与权威性边界

**自恢复提交 [`2e7a2eb27c10d3b90b29ed338df0f1a14a978744`](https://github.com/NewDanYang/CICC-drone-attack/commit/2e7a2eb27c10d3b90b29ed338df0f1a14a978744) 起，`official_baseline/catkin_ws/src/ego-planner/src/planner/bspline_opt/` 的九个原有源码及构建配置文件已恢复为本仓库污染前的官方原始快照，可作为该子目录的只读对照；此结论仅适用于这些文件，后续使用需复核版本和下列校验值，不代表 `official_baseline/` 的其他子目录已经逐一鉴定。**

来源为 `add1a2a` 的父提交 `5fd53fe958934bb3aa8dd4834b798c13d4a8673f`，与最初引入官方快照的提交 `045155040198da0a0a19dcad14797fa17d6a45e4` 在该子目录的内容一致。Git 历史显示 `add1a2ae7826f8881c12fce2e023e00ba79c1438` 将方向 A 的四个候选文件写入了该目录；包含该改动、尚未包含本次恢复的版本不能将这四个文件作为官方原版。

## 四文件校验

原始 MD5 的依据是 [deploy_v1_manifest.json](../v4_innovation_timing/path_planning_experiment/evidence/deploy_v1_manifest.json) 的 `original_md5`。2026-10-24 审计的 `evidence/source_manifest.json` 记录的是当时被审计文件的实际哈希，不含 `original_md5` 字段，也不是本次恢复应匹配的原始值；历史审计记录保持原样。

下表路径均相对于 `catkin_ws/src/ego-planner/src/planner/bspline_opt/`：

| 文件 | 恢复后 MD5（与 `original_md5` 一致） |
|---|---|
| `src/bspline_optimizer.cpp` | `a968a5e81b3799c2ed68d75b582f5fc4` |
| `include/bspline_opt/bspline_optimizer.h` | `2d2615f01a3834ac24104360e43426b6` |
| `CMakeLists.txt` | `0fc1056df778674f1571a427bab78562` |
| `package.xml` | `da5f06411d24160a919de5ba17d4c4f2` |

历史 Git blob 使用 LF，而原部署清单按 CRLF 文件计算 MD5。本次仅将污染前源码恢复为清单对应的 CRLF 字节，未做其他内容修改；这四个文件使用局部 `.gitattributes` 的 `-text` 保存原始字节。工作副本、Git 提交和 `git archive` 导出的四文件 MD5 均已核对一致，避免只在 Windows 检出时匹配、下载归档后又不匹配。该子目录其余五个原有文件未修改，九文件均按忽略 CRLF/LF 差异的方式与污染前提交逐一核对。

## 方向 A 的独立保存与使用

方向 A 的四个候选文件现在完整保存在 [path_planning_experiment/payload_v1/](../v4_innovation_timing/path_planning_experiment/payload_v1/README.md)，其 MD5 均匹配同一部署清单的 `deployed_md5`。已有补丁脚本、部署清单和历史证据未修改；实验报告只更新了源码入口及本次存储位置修订说明。临时副本上的 v1 安装与回滚均通过四文件 MD5 检查，v2 继续使用同一候选源码加参数切换脚本。

今后实验应在独立工作副本中进行，使用上述实验目录作为候选源码入口；请勿将实验补丁、生成结果或调参改动写回本目录。需要扩展其他子目录的可信范围时，应另外记录来源提交与校验依据。

完整校验值及本次离线检查结果见 [baseline_restore_20261027.json](../v4_innovation_timing/path_planning_experiment/evidence/baseline_restore_20261027.json)。本次没有执行 ROS 编译、连接服务器、部署代码或运行新仿真；这里确认的是仓库源码身份，不是服务器当前运行版本。

撤销源码恢复可使用 `git revert 2e7a2eb27c10d3b90b29ed338df0f1a14a978744`；这会重新引入已知的团队候选版本并撤销独立 payload，届时本页的原始代码声明和 MD5 表不再适用于回退后的文件，应同步修订说明。
