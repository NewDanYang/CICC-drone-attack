# 方向 A：v1/v2 实验源码封存

这里保存方向 A 两版实验共用的四个源码/配置文件，路径布局与 `ego-planner` 根目录一致。源码取自历史提交 `add1a2ae7826f8881c12fce2e023e00ba79c1438`，按当时部署使用的 CRLF 字节保存，四个 MD5 均与 [deploy_v1_manifest.json](../evidence/deploy_v1_manifest.json) 的 `deployed_md5` 一致；`.gitattributes` 的 `-text` 防止 Git 自动改写这些文件的换行。

2026-10-27 恢复 `official_baseline/` 时，将此前只存放在该目录的候选源码独立封存到这里。原 [v1 脚本](../patches/patch_balloon_clearance_cost_v1.py) 是带 MD5 门禁的安装器，并不会生成候选 C++；现在其 `--payload-root` 可直接指向本目录。v2 使用同一份源码，仅由 [v2 脚本](../patches/patch_balloon_clearance_cost_v2.py)切换 ROS 参数。

在仓库根目录，以下命令仅演示对**已有的独立临时工作副本**安装文件；该副本需先放入四个原始文件，其 MD5 必须匹配 `original_md5`，且备份及清单路径不能已存在：

```bash
python v4_innovation_timing/path_planning_experiment/patches/patch_balloon_clearance_cost_v1.py \
  --source-root ../direction-a-scratch/ego-planner \
  --payload-root v4_innovation_timing/path_planning_experiment/payload_v1 \
  --manifest ../direction-a-scratch/deployment.json
```

对同一临时副本回滚：

```bash
python v4_innovation_timing/path_planning_experiment/patches/patch_balloon_clearance_cost_v1.py \
  --source-root ../direction-a-scratch/ego-planner \
  --manifest ../direction-a-scratch/deployment.json --rollback
```

本次在独立临时目录实际完成了上述安装和回滚：安装后四文件匹配 `deployed_md5`，回滚后四文件匹配 `original_md5`，见 [恢复校验记录](../evidence/baseline_restore_20261027.json)。这些是文件完整性与安装器检查，没有进行 ROS 编译、服务器部署或新增仿真。原实验数据与适用边界仍以 [REPORT.md](../REPORT.md) 为准；`official_baseline/` 继续作为只读对照，实验改动应在独立副本进行。
