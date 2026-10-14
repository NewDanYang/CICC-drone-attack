# 规则合规修改（2026-10-13，仿真初赛）

依据：赛事规则原文 3.2、4.1–4.4（`打击.pdf`）。本目录的候选改动已完成离线测试。

> **2026-10-14 更新：候选版曾上机试部署，随后已回滚。** 首局红色 ArUco 窗口
> 0.561 s，高于旧版 9 局的 0.106–0.217 s；因此没有继续紫、蓝局。
> 新措辞严格正确率为 31/54，未达 95%。当前服务器运行的是部署前的三个文件。
> 原始证据和结论边界见 [`../reports/rule_compliance_20261014/REPORT.md`](../reports/rule_compliance_20261014/REPORT.md)。

## 规则逐条状态

| 规则 | 风险 | 状态 | 处理 |
|---|---|---|---|
| 开赛 5 分钟无人机未动 → 本轮结束 | 大模型两次错色或无 ```command 块时**不发布任何命令**，整轮 0 分 | **候选已回滚** | `mission_once.py`：最多 3 次 / 60 s 重试，最后仍按原样发布最接近的一次 |
| 九格语义解析必选，不得手写复合接口 | 校验逻辑若改写命令即越界 | 合规 | 命令只来自大模型输出，校验只做检查、重试、选择，**从不生成或改写命令** |
| 感知结果窗口（每阶段 −5） | ArUco 窗口默认关；检测窗口在 headless 配置下关 | **候选已回滚** | ArUco 与 `Detection + Color`（方框 + 气球 bbox）窗口默认开、主线程绘制；ArUco 检出后保留"ID: n"画面 |
| 降落标志检测窗口 / 视觉反馈 | 降落完全没有感知 | **未修** | 第二部分：降落标志检测 + 窗口 + 视觉对准 |
| 禁止预设位置点（审查后每阶段 −5） | BT 中的固定坐标；红区 yaw=π、接近高度 1.5 是新增预设 | **未修** | 第一部分改红区为感知扫描定向；第二部分准备审查说明 |
| 碰撞每物体 −5，两物体本阶段 0 | 9 局中 7 局击球后触发边界恢复；红、蓝区共用击球点，有误击风险 | **未修** | 第一部分：接触后刹车，三球全在场时零误击 |
| 赛前 `rostopic echo /mavros/setpoint_raw/local` 展示 | — | 合规 | `sim_env_start.sh` 已开 Setpoint Monitor 终端，见检查单 |
| 禁止改仿真速度 | — | 合规 | 未改动 |
| 10 分钟限时；计时到电机停转 | — | 合规 | 正式试验 ≤300 s；降落 9/9 解除武装 |

## 改动内容

| 文件 | 原 MD5 → 新 MD5 | 生成方式 |
|---|---|---|
| `/home/ubuntu/model/mission_once.py` | `4b0ae381` → `e7bb1627` | `patches/patch_mission_publish_fallback.py`（源 MD5 不符时拒绝修改） |
| `catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py` | `0f15e84b` → `43c3bc40` | 本 PR 以 `deploy/aruco_detect_node.py` 作为已核对的候选 payload；旧版由服务器回滚备份保存 |
| `catkin_ws/src/object_det/scripts/det_color.py` | `9eda7268` → `348dd7d0` | `patches/patch_det_color_window.py`（源 MD5 不符时拒绝修改） |

三个都是 Python 文件，**不需要 catkin_make**，但要重启节点（大模型进程也要重启）。

### `mission_once.py` 的行为变化
- 每次回答都检查三项：有没有 ```command 块；命令名是否都属于 `takeoff/cross_frame/detect_aruco/return_cross_frame/hit_balloon:<red|purple|blue>/land`；指令里只点名一种颜色时，`hit_balloon` 是否恰好是这个颜色。
- 颜色识别扩展到"红色气球、红色的气球、红颜色的气球、红气球、red balloon"。指令里出现两种颜色（例如"不要碰蓝色，扎破红色"）时不做颜色校验。
- 不合格就带提示重试。`MISSION_MAX_ATTEMPTS`（默认 3）和 `MISSION_RETRY_BUDGET_S`（默认 60）都可以通过环境变量调整。
- 都不合格时，发布未知命令最少的那次回答，**原样发布**。宁可只丢气球阶段 25 分，也不因无人机不动而丢掉整轮。
- 一次 ```command 块都拿不到时仍然不发布，因为我们不能自己编命令。这种情况会打日志，需要操作员重新输入指令。

### 窗口的行为变化
- 图像回调只负责把标注好的画面交给主线程，`imshow/waitKey` 只在主线程调用，避免窗口拖住回调。这也正是 ArUco 回调停摆假设 1 怀疑的机制。
- 显示出错时记录错误，检测照常运行，不会因为窗口拖垮识别。
- `show_window` 和 `debug_display` 的默认值改为 true。配置里**显式**写 false 时仍然生效，所以上机必须核对实际参数（见下）。

## 离线测试

```bash
cd v3_stability/rule_compliance
PYTHONIOENCODING=utf-8 python tests/test_mission_once_fallback.py   # 18/18 通过；同一组用例跑旧版有 7 项失败
PYTHONIOENCODING=utf-8 python tests/test_aruco_display_loop.py      # 6/6 通过
```

测试范围有限：大模型、ROS、OpenCV 窗口都用桩替代。**不能**证明真实大模型在新指令下的正确率，
也不能证明窗口开着时 ArUco 和检测的时延不变。这两点必须上机验证。
`det_color.py` 只做了编译检查和 diff 审阅，它的显示循环与 ArUco 的同构，但没有单独测试。

## 部署（服务器开机、确认无人使用后）

```bash
# 本地
for f in mission_once.py aruco_detect_node.py det_color.py deploy_rule_compliance.sh; do
  MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py put \
    v3_stability/rule_compliance/deploy/$f /tmp/rule_compliance/$f
done
MSYS_NO_PATHCONV=1 python v3_stability/tools/srvctl.py sh 'bash /tmp/rule_compliance/deploy_rule_compliance.sh'
# 然后按 AGENTS.md §2.3 重启仿真环境
```

脚本会做这些检查：有正式试验锁时拒绝；三个线上文件的 MD5 必须与上表"原 MD5"一致，否则一个都不改；
备份到 `/home/ubuntu/rule_compliance_backup_<ts>/` 并生成 `restore.sh`；复制后再校验一次 MD5。
本地已在沙盒中演练过部署、重复部署被拒、有锁被拒、回滚四种情况。

**回滚**：`bash /home/ubuntu/rule_compliance_backup_<ts>/restore.sh`，然后重启仿真环境。

## 上机验证（不做完不算修好）

1. `rosparam get /object_detection/visualization/show_window` 必须是 `true`。如果是 false，说明启动用了 headless yaml，要改回官方 `detection_params.yaml`。
2. 截图（服务器上 `DISPLAY=:20`，用 `import -window root` 或 `xwd`）确认两个窗口都在：
   - `Detection + Color`：穿框和击球阶段有方框、气球的 bbox；
   - `ArUco Detection (Python)`：二维码阶段之后停留在"ID: 35"。
3. 至少跑 3 局正式试验，与 2026-10-13 那 9 局对比：ArUco 窗口时长（0.105–0.217 s）、`callbacks/s`、击球结果、总用时。窗口开启后任何一项明显变差都要回滚并报告。
4. 大模型兜底：用一句故意不点名颜色、措辞陌生的指令跑一次，确认 `[命令校验]` 日志和发布行为符合预期。

## 比赛当天检查单（初稿）

- [ ] 开赛前已加载好模型（`mission_once.py` 的 `[3/3] 模型就绪`），以交互模式等待输入
- [ ] Setpoint Monitor 终端里 `/mavros/setpoint_raw/local` 在持续刷新，可以给裁判看
- [ ] `Detection + Color` 和 ArUco 两个窗口都在屏幕上（ArUco 窗口在检测开始后才出现）
- [ ] `rosparam get /object_detection/visualization/show_window` 为 true
- [ ] 安全参数 `safety/*` 是默认值（`y_max=3.0`），不是越界测试用的值
- [ ] 没有残留锁 `/tmp/tcei_formal_trial.lock`、`/tmp/tcei_sim_environment.lock`
- [ ] 输入指令前确认题目颜色，发布后核对日志里的 `hit_balloon:<色>`
- [ ] 准备好向评委说明控制链：大模型 → `/mission_command` → `bt_ros` 逐条命令生成 BT 节点 → `/mavros/setpoint_raw/local`
