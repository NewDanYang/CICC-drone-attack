#!/bin/bash
set -euo pipefail
ROOT=/root/gpufree-data/mm40_spatial_clean
export MM38_RUN_ROOT="$ROOT"
export MM38_TARGET_MODULES='llm\..*layers\.\d+\.self_attn\.(q_a_proj|q_b_proj|kv_a_proj_with_mqa|kv_b_proj|o_proj)'
export MM38_LEARNING_RATE=5e-5
export PATH="/root/gpufree-data/mm36_lora_v2/venv/bin:$PATH"
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TORCH_EXTENSIONS_DIR="$ROOT/torch_extensions" MAX_JOBS=4
mkdir -p "$ROOT" "$ROOT/tensorboard" "$ROOT/output_lora"
torchrun --nproc_per_node 1 --nnodes 1 --node_rank 0 --master_addr localhost --master_port 6040 \
  "$ROOT/tools/train_fixed_native.py" \
  --model_name_or_path /home/ubuntu/model/FM9G4B-V \
  --data_path "$ROOT/data/train.json" --eval_data_path "$ROOT/data/validation.json" \
  --remove_unused_columns false --label_names labels --prediction_loss_only true \
  --bf16 true --bf16_full_eval true --fp16 false --fp16_full_eval false \
  --do_train --do_eval --tune_vision false --tune_llm false --use_lora true \
  --lora_target_modules "$MM38_TARGET_MODULES" --model_max_length 2048 --max_slice_nums 9 --max_steps 1200 \
  --eval_steps 200 --output_dir "$ROOT/output_lora" --logging_dir "$ROOT/tensorboard" \
  --logging_strategy steps --per_device_train_batch_size 1 --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps 1 --evaluation_strategy steps --save_strategy steps --save_steps 200 \
  --save_total_limit 2 --learning_rate "$MM38_LEARNING_RATE" --weight_decay 0.0 --adam_beta2 0.95 \
  --warmup_ratio 0.05 --lr_scheduler_type cosine --logging_steps 1 --gradient_checkpointing true \
  --deepspeed /root/gpufree-data/mm36_lora_v2/configs/ds_config_zero2_cpu.json \
  --report_to tensorboard --load_best_model_at_end true --metric_for_best_model eval_loss \
  --greater_is_better false --seed 4001
