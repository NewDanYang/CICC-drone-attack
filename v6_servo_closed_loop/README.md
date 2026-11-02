# v6_servo_closed_loop

FM9G 多模态检测 → 无人机击球闭环的桥接层实现（第 6 版，已上服务器跑过 5 局正式试验）。

- 设计依据与取证：[REPORT.md](REPORT.md)
- 上一版方案（未上线，仅纸面）：[`../v5_never_blind/`](../v5_never_blind/)

## 目录

```
code/       部署到 /home/ubuntu/model/fm9g_perception/ 的 8 个模块（原样快照）
patches/    部署脚本与 manifest（deploy_v2.py / build_v2.sh / make_manifest.py）
tools/      离线取证脚本（试验摘要、HSV 真值、对账、静止拟合、发布窗探针）
evidence/   五局正式试验的记录
```

## 部署文件 md5（2026-11-02 12:47 服务器实测）

| 文件 | md5 |
|---|---|
| localizer.py | `8d329caed84b8d1c7eb4c7c20c3fb06f` |
| tracking.py | `596009abe3dc4e6bea0c07e372ba239e` |
| runtime.py | `5790baaaaedab5980590be4e6b29ccd8` |
| refinement.py | `af0ad29d1fa4a43fc4e18e77fdeb30cf` |
| geometry.py | `58db79f8cb33c10c6bc4d7aad60e54dc` |
| presence.py | `a06a9eafb256b18f5910cd0a5225761d` |
| v5_guard.py | `079cc32a7d65afa26df36cb131f7cba8` |
| v6_estimator.py | `af38fe099a28c8fabfc54ff5acdf9ac7` |

未改动：`mission_once.py` `de03cd1a5687f7bc0664ea52f3cd095f`、`bt_ros.cpp` `9a1e8d2a5913968b1c2300cad1dc02f7`、
插件 `multimodal_target_tracker.so` `2a2e1b7fc0b2ca37291ecbef97ade06f`、`bt_ros` 二进制 `1f1592dc8d33613bf4b772a4eb2f6dfb`。

## 部署（顺序不能变）

`deploy_v2.py` 有两处 md5 校验：**:65** 校验 `v2/` 源文件、**:111-113** 校验**已安装**的模块。
所以改源码后必须先让两侧都与新 manifest 一致：

```bash
# 1) 上传新模块到 v6_stage/v2/ 与 /home/ubuntu/model/fm9g_perception/
# 2) 重算 manifest
cd /home/ubuntu/multimodal_v2/v6_stage/patches && /usr/bin/python3 make_manifest.py
# 3) 先回到 baseline（此时两侧已与新 manifest 一致）
pkill -x bt_ros; sleep 2
bash /home/ubuntu/multimodal_v2/v6_stage/patches/build_v2.sh baseline /home/ubuntu/multimodal_v2_backup_20261026T0009
# 4) 再装 candidate
bash /home/ubuntu/multimodal_v2/v6_stage/patches/build_v2.sh candidate /home/ubuntu/multimodal_v2_backup_20261026T0009
```

## 跑一局

```bash
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
source /opt/ros/noetic/setup.bash
rosparam set /visual_servo/approach_area_threshold 0.02
rosparam set /visual_servo/forward_velocity 0.30
cd /home/ubuntu/tcei_baseline_tools
setsid nohup bash ./run_formal_trial.sh purple > /tmp/trial.log 2>&1 < /dev/null &
```

## 回滚

```bash
bash /home/ubuntu/multimodal_v2/v6_stage/patches/build_v2.sh baseline /home/ubuntu/multimodal_v2_backup_20261026T0009
```
