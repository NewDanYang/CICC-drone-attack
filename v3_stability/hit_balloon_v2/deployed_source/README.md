# 2026-10-12 服务器实际部署快照

下列 C++、launch 和检测节点文件由 `srvctl.py get` 从服务器字节安全下载；`mission_once.py` 是从实取原件经 MD5 校验的补丁脚本生成，再上传并由服务器验证 MD5/语法。不是从 Git 历史猜测出的部署状态。

| 文件 | 服务器原路径后缀 | MD5 |
|---|---|---|
| `visual_servo.deadzone_only.cpp` | `src/nodes/action/visual_servo.cpp`，居中门控前 | `4d9a99091f3d1f68facb743d2fab14e2` |
| `visual_servo.gate_only.cpp` | `src/nodes/action/visual_servo.cpp`，只加居中门控 | `74802b9d2082aa408b97b555685aee2a` |
| `visual_servo.guard_only.cpp` | `src/nodes/action/visual_servo.cpp`，红球朝向门控后、位置保持前 | `418ae9129a266bc4ac3c013f4232011b` |
| `visual_servo.cpp` | `src/nodes/action/visual_servo.cpp`，当前位置保持版 | `e440050ecfc06657d5ac4b472411fef6` |
| `visual_servo.h` | `include/nodes/action/visual_servo.h`，当前位置保持版 | `d3324b0458b2160102f9bbf44546d035` |
| `bt_ros.cpp` | `src/bt_ros.cpp`，传入目标颜色 | `989415357ddcc33777989026ce873eca` |
| `llm_mission.yaw_only.launch` | `launch/llm_mission.launch`，红区 yaw 补丁后 | `985fd7628fb4af120e63fdf6cea4e757` |
| `llm_mission.high_end.launch` | `launch/llm_mission.launch`，红区全程 z=1.5 | `9088ac755b09854976bf62a643ddf4bd` |
| `llm_mission.launch` | `launch/llm_mission.launch`，红区高空过境、末端 z=1.0 | `3fdc18d0f61052da1e93456078370926` |
| `det_color.py` | `src/object_det/scripts/det_color.py`，只读取证、未修改 | `9eda726899abaf4f951f6b03a08c11ad` |
| `mission_once.before_color_guard.py` | `/home/ubuntu/model/mission_once.py`，模型错色修复前 | `dcc050dd1daa1792a7312345932d0fcb` |
| `mission_once.py` | `/home/ubuntu/model/mission_once.py`，当前颜色校验版 | `4b0ae381b683b7c38d30baf808ed1346` |

源码差异的可重复构造步骤在相邻 `patches/` 的脚本中。launch 保留原 CRLF 和 UTF-8 中文注释；不能通过 shell `cat >` 重建。服务器备份与回滚路径见主报告。位置保持版插件 MD5 为 `1991d332fb6a8e28ca98d16b479de466`，任务节点重启后曾由 `/proc/<pid>/maps` 确认加载。后续场景重启时 SSH 端口拒绝连接，尚未核实该次重启状态。
