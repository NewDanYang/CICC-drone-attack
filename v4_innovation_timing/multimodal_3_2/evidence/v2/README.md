# 第二次实施的真实证据

- `demo_review.json`：三色演示的人工核对，具体决策 ID、实际窗口、控制指向和反例。演示不进入 3.3 分母。
- `review/`：原始 X11 截图的原字节副本；含紫色墙面漂移反例，不只展示成功框。
- `trials/*.tar.gz`：每个调试/演示/诊断局独立归档。包含原始 observer JSONL、原生 telemetry JSONL/日志/规划 CSV、全部模型源 PNG 与实际送模区域 PNG、全部窗口、部署 MD5、飞后 GC 和对象列表；SHA256/字节数见 `development_receipts.json`。
- 服务器各原始 session 的 `audit/frames` 保留观察器全部已保存 JPEG。观察器在击球段按 0.085 s 最小间隔尝试采集，实际频率受图像到达与调度影响，不是传感器零丢帧全量录像；原始 header_stamp/seq 可复算时间间隔。Git 包保留这些 JPEG 每十张中的一张；`MANIFEST.json` 对**所有已存原件**记录 SHA256、字节数以及是否装包。缺失图像可在列出的服务器路径按哈希取回。所有实际模型输入源图和区域图均完整装包。
- `development*.tar.gz`、`additional_development.tar.gz`、`graph_development.tar.gz`：真实帧离线开发探测和复现脚本；这些帧已经用于调参，不是盲测集或正式识别准确率。
- `red_demo5_gc_crash.log`：红色演示后 GC 与预先注册的对象查询相互影响的 UE 原始崩溃日志。不能把该缺失物理结果补为成功或漏击。
- `guard_checks.log`：14 项接口/失效保护检查；stub 检查不代表视觉或实飞性能。
- `deployment_package.tar.gz`：实际上传的 39,710 字节部署包，SHA256 `54ccbd05d8d552f52392aa1c194c71c5aa968b6ef0685aa68e9dfce1d8fa157d`；单文件 MD5 见 `../../v2/manifest.json`。

输入保存的准确范围：所有送模源帧 PNG 和分割区域的实际像素 PNG 均完整装包。均匀视图、确认框及其颜色追问没有为每个 processor 项各存一份 PNG；它们可由源帧、日志中的裁剪坐标/批次索引及逐项像素 SHA256 无损重建。不能把数百个 processor 图像项说成数百张独立相机帧或数百个单独图像文件。

解包单局后可以不加载模型、不连 ROS 重新计算接入统计：

```bash
tar -xzf trials/对应单局.tar.gz -C 一个空目录
python ../../tools/summarize_session_v2.py 一个空目录/session
python ../../tools/control_links_v2.py 一个空目录/session
```

前一工具会重新检查实际窗口 PNG 的中心画面是否非黑，不把 WINDOW_READY 或黑色窗口算成有效截图。后一工具按决策 ID 串联源图、模型选择、像素消费、原伺服和紧随其后的执行指令；窗口可能有数百毫秒捕捉差，保留真实时间，不伪造同步。

固定版本 3.3 的原始证据与最终统计放在 `../../../multimodal_3_3/evidence/v2/`，采用单独的 9+9 分母。全部结论以两份最终 REPORT 为准，3.1 与全类别加分门槛仍未补齐。
