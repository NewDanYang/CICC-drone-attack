# 证据索引

- `reference/provenance.json`：用户提供的官方手册来源及 SHA256、官方源码提交。
- `reference/manual_training_excerpt.txt`：手册训练部分文本（包含代码换行）。
- `reference/finetune_lora.manual.sh`：从手册原文提取的启动命令；官方仓库该提交没有此文件，不能冒称下载到了同名脚本。
- `reference/official_training.tar.gz`：官方提交的 FM9G4B-V 训练源码、依赖清单、README 原件。
- `reference/launcher.diff`：执行脚本相对手册的路径、预算和日志/显存适配。
- `data/pool.json`：旧对照局真实相机帧及时间戳严格相同的离线 YOLO 标注提议，含原始归档路径、成员名和图像 SHA256。
- `data/cases.json`：经单 AI 视觉复核的最终问答标签；唯一误分类提议 026 被剔除；原有人工正框和负例保留来源。
- `data/dataset_receipt.json`：整局划分、实际图像数/问答数所需口径、JSON 散列。
- `data/train.json` / `validation.json` / `test.json`：官方单图单轮会话格式。一张图可以产生多个问答，不等于多个独立样本。
- `dataset.tar.gz`：上述 JSON、全部实际训练/验证/留出原始相机图像和上传时工具副本。运行代码以 `tools/` 及最终清单为准。

训练与评估只读取原始相机图像；带黄色框的复核联系表不进入模型。传统检测器只出现在既有离线消息提议中，运行脚本不加载 YOLO、不连接 ROS、不查 UE 真值。
