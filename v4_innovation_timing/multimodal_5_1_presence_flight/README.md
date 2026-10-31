# 5.1 P12e 接入包

`v2/` 是从 3.2 第二次实施包派生的候选 runtime，`patches/` 包含 MD5 守卫部署、编译和回滚脚本，`tools/` 包含 P12e 状态机、FastPresence parity 检查、源码检查和录制帧 smoke 驱动。

服务器上的候选已经完成源码激活和 `catkin_make --pkg mission_pkg` 编译。录制帧 smoke 仍未达到 P12e 框中心 ≤3 px 的离线门，因此没有启动阶段 C 仿真飞行。

候选回滚：

```bash
cd /home/ubuntu/multimodal_v2/p12e_stage_b
bash patches/build_p12e.sh baseline /home/ubuntu/multimodal_v2/p12e_backup_20261031
```
