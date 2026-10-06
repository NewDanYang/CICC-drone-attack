V1 云端测试记录

测试日期：2026-10-05（算力自由云服务器）  
版本：V1 安全边界恢复；工作区编译成功  
仓库操作：未修改 GitHub 原仓库。云端运行工作区覆盖了 V1 三个文件，并保留了覆盖前备份。

## 数据完整性

三色归档 SHA256：

```text
01b56e5db2ae815984bd0d0edede0d56711efe7e98cbbe5d06f2cd281504c78c
```

三轮测试使用的安全参数一致：

- 边界：X[-1, 6]、Y[-3, 3]、Z[-0.1, 2.5] m
- 恢复目标裕量：0.30 m
- 释放裕量：0.15 m
- 恢复确认时间：0.50 s

## 三色结果

| 颜色 | 用时 | 结果 | 已完成阶段 | 失败或限制 | V1 恢复证据 |
|---|---:|---|---|---|---|
| 红色 | 151.073 s | `mission_success=false` | 起飞、穿框、二维码、返框、降落 | 击球阶段没有被测试器确认；日志显示视觉追踪丢失目标 | 未触发，`safety_boundary_triggered=false` |
| 紫色 | 59.000 s | `mission_success=false` | 起飞、穿框 | ArUco 识别等待 20 秒后失败；任务返回 `FAILURE`，之后人工降落 | 未触发，`safety_boundary_triggered=false` |
| 蓝色 | 66.109 s | `mission_success=false` | 起飞、穿框 | ArUco 识别等待 20 秒后失败；任务返回 `FAILURE`，之后人工降落 | 未触发，`safety_boundary_triggered=false` |

### 红色

观察器记录 `bt_success=true`，但 `mission_success=false`，失败阶段为 `hit_balloon`。日志反复出现 `Target lost` 和 `No target detected`，随后视觉追踪进入悬停；测试器没有确认击球成功。自动降落阶段有成功记录。没有出现 `[SafetyRecovery]`、越界或恢复完成日志。

### 紫色

观察器记录 `bt_success=false`、`mission_success=false`，失败阶段为 `detect_aruco`，原因是 `mission_result=FAILURE`。ArUco 节点等待 20 秒后关闭检测，行为树返回失败。任务没有进入返框、击球和自动降落；飞机保持悬停指令，随后人工切换 `AUTO.LAND` 降落。日志没有 `[SafetyRecovery]` 或边界恢复记录。

### 蓝色

观察器记录 `bt_success=false`、`mission_success=false`，失败阶段为 `detect_aruco`，原因是 `mission_result=FAILURE`。ArUco 检测等待 20 秒后失败，任务没有进入返框、击球和自动降落；随后人工切换 `AUTO.LAND`，并确认飞机解除解锁。日志没有 `[SafetyRecovery]` 或边界恢复记录。

## 结论

三轮证明了 V1 工作区已加载并运行，安全参数也已生效；但本次任务没有产生越界事件，因此**没有覆盖到 V1 防穿模/边界恢复分支**。三色任务均不能作为完整任务成功样本：红色未确认击球，紫色和蓝色在 ArUco 阶段失败。紫色、蓝色失败后均需要人工切换 `AUTO.LAND`，说明失败任务的自动收尾仍需单独修复和验证。

若要验证 V1 恢复逻辑，需要单独设计一个可控的越界目标测试，并同时确认失败任务会自动进入安全降落或停止控制。

归档中包含三轮原始 JSONL、遥测、规划摘要、版本哈希、构建日志、V1 源文件和部署前备份。
