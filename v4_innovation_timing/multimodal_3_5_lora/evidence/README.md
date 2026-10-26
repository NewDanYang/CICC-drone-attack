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

## 训练、留出对照与完整性

- `startup_evidence.tar.gz`：FP16 dtype冲突、BF16显存限额失败、第三次226步后实例中断的原始日志/配置/资源记录，以及隔离环境安装、CUDA继承库链接、官方预处理312条检查的记录。失败均保留，第三次丢失更新不算最终模型。
- `training_receipt.json`：1200步早停、以验证loss选800步、每次验证loss、整卡显存/CPU RSS峰值、选中适配器大小及MD5/SHA256。
- `selected_adapter_config.json` / `parameter_inventory.json`：实际r/alpha/模块及可训练参数口径；`checkpoint200_update_proof.json`只抽查第0层B矩阵的更新，不是逐层梯度正确性证明。
- `training_environment.json`：正式训练和配对推理的关键依赖版本。
- `heldout/base_test/`、`heldout/adapter_test/`：各67对象的原始回答/时延/提示词散列、逐条计分、汇总、实际输入配置。每模型134次真实图像processor调用。
- `heldout/paired_analysis/paired.csv`、`paired_summary.json`：按颜色、旧试验局、大小、手工框来源汇总；所有原定门的布尔判断。
- `heldout/error_diagnostics.json`：非法JSON、负例错误、几何失败类型、区域改善/退步对象，以及同49对象的配对中心偏差。属于结果后解释，不用于修改门槛或重选模型。
- `local_rescore_check.json`：本地从原始回答重新计算，与服务器全部汇总/门判断一致。
- `runtime_after.json`、`runtime_integrity_comparison.json`、`base_weights_after.sha256`：26个运行/基座源码配置文件无差异、四个关键demo包版本无变化、基座大权重散列不变、官方训练源码无已跟踪差异。
- `final_run.tar.gz`：完整有效训练日志/资源CSV/原始训练状态、800步配置/标记、实际运行脚本、配对推理日志/回答和完整性记录。SHA256 `49998382f1499a8fe5145a9b60110ca7ccc50937b1380e95637eb00ddd4a031f`，243,047字节。包内49个原始文件散列见 `final_run_manifest.json`，已逐项核对。
- `delivery_manifest.json`：本轮交付文件的MD5和SHA256（清单自身除外）。

早期 `tools.tar.gz` 和 `dataset.tar.gz` 中的工具是上传时快照，不能代替最终执行脚本。最终包内实际 `finetune_lora.sh`、`train_budget.py`、CPU配置、评估/计分脚本与提交的版本一致。包内服务器遗留的 `prepare_launcher.py` 是旧版**未调用的生成器**；正式兼容脚本在本地生成后逐字节上传，手册原文与实际启动脚本的差异已保存为 `reference/launcher.diff`。不要拿早期生成器覆盖最终配置。

## 大权重位置

不将1.3GB适配器或约11GB优化器检查点提交Git。服务器持久卷：

```text
/root/gpufree-data/tcei_lora35/output_lora/checkpoint-800/
  adapter_config.json
  adapter_model.safetensors
  trainer_state.json
  experiment_complete.json
  global_step800/   # 完整训练恢复状态
```

适配器SHA256 `696615aa92f09dc3be22db8e84ed9d8201b9375789e20140dceb0dc38a46ff73`，MD5 `dac2201c837e6406a0534180f5563b79`。根目录最后保存的适配器与800步文件散列相同。该目录不是线上入口，模型未部署；所有推理进程已退出，不需要回滚正式比赛文件。
