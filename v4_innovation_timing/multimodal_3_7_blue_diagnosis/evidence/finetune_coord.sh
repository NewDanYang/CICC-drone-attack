#!/bin/bash
set -euo pipefail
export PATH="/root/gpufree-data/mm36_lora_v2/venv/bin:$PATH"
export OMP_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TORCH_EXTENSIONS_DIR="/root/gpufree-data/mm37_coord_only/torch_extensions"
export MAX_JOBS=4
torchrun --nproc_per_node 1 --nnodes 1 --node_rank 0 --master_addr localhost --master_port 6013 \
  /root/gpufree-data/mm37_coord_only/tools/train_budget.py \
  --model_name_or_path /home/ubuntu/model/FM9G4B-V \
  --data_path /root/gpufree-data/mm37_coord_only/data/train.json \
  --eval_data_path /root/gpufree-data/mm37_coord_only/data/validation.json \
  --remove_unused_columns false --label_names labels --prediction_loss_only true \
  --bf16 true --bf16_full_eval true --fp16 false --fp16_full_eval false \
  --do_train --do_eval --tune_vision true --tune_llm false --use_lora true \
  --lora_target_modules "llm\\..*layers\\.\\d+\\.self_attn\\.(q_proj|k_proj|v_proj|o_proj)" \
  --model_max_length 2048 --max_slice_nums 9 --max_steps 1200 \
  --eval_steps 200 --output_dir /root/gpufree-data/mm37_coord_only/output_lora \
  --logging_dir /root/gpufree-data/mm37_coord_only/tensorboard \
  --logging_strategy steps --per_device_train_batch_size 1 --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps 1 --evaluation_strategy steps --save_strategy steps \
  --save_steps 200 --save_total_limit 2 --learning_rate 1e-6 --weight_decay 0.1 \
  --adam_beta2 0.95 --warmup_ratio 0.01 --lr_scheduler_type cosine --logging_steps 1 \
  --gradient_checkpointing true --deepspeed /root/gpufree-data/mm37_coord_only/configs/ds_config_zero2_cpu.json \
  --report_to tensorboard --load_best_model_at_end true --metric_for_best_model eval_loss \
  --greater_is_better false --seed 3701
