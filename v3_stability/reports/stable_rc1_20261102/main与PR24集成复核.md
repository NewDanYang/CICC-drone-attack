# main 与 PR #24 集成复核

已以 main `99096001661c8bcb45890792fe0126c044a8f91d` 为底，选择性集成 PR #24 `29eec32c9262b13713114fc8e6162d75cd0793b1`。GitHub 本次只读复核仍为相同 base/head；PR 未合并。分支 release/stable-rc1 尚未提交或推送。

此前旧服务器 mission_pkg 整包来源不清的做法已被替换：独立 workspace 从仓库物料化 mission_pkg/object_det，并加入 main 的安全恢复、稳定等待、增强 ArUco 和历史 launch，再 stage PR #24 的配套控制器与插件。稳定等待四参数、颜色检测配置和模型身份均已进入实际运行链路。TargetDetectorBase 采用仓库 main 版本；PR #24 Tracker 保留自身消息处理实现。

构建、11 插件树预检通过；离线 156/2/0（失败为历史原始日志缺失），隔离 ROS 14/14。本局实际运行 /proc bt_ros 与七库验证通过。三个 EGO 值 0.30 和 VisualServo 1.00/1.50/1.20 实测一致。PR #21/#22/#23 未进入飞行链路。

EGO 与 sensor underlay：568 个 main 文件中 73 精确相同、494 仅 CRLF 差异、缺 1 个 .gitattributes。包含 Config.json、EGO launch 和实际运行传感器 Python 入口。该比较证明源码/配置一致，不能证明本轮重建 EGO；EGO 二进制仍来自保留 underlay。

服务器重新生成的 22 文件发布清单已取回并同步本地，列出的每个文件字节均匹配。早期来源核查已另存 integration-source-audit-before-rematerialization.json；integration-source-audit.json 现已更新为本次物料化、发布清单、underlay 审计与真实运行身份的对应关系。

最新红色诊断前四阶段成功，红球阶段超时失败，安全恢复降落解除武装。日志/rosbag/相机回放已保留。没有将失败飞行或 PR #24 的历史红球成功当作当前版本验收；当前正式 0/9。详见当前进度和红色候选试跑报告。
