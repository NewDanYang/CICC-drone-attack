#!/bin/bash
set -euo pipefail
export PATH="/root/gpufree-data/tcei_lora35/venv/bin:$PATH"
export OMP_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TORCH_EXTENSIONS_DIR="/root/gpufree-data/tcei_lora35/torch_extensions"
export MAX_JOBS=4
GPUS_PER_NODE=1
NNODES=1
NODE_RANK=0
MASTER_ADDR=localhost
MASTER_PORT=6012

MODEL="/home/ubuntu/model/FM9G4B-V"
DATA="/root/gpufree-data/tcei_lora35/data/train.json"
EVAL_DATA="/root/gpufree-data/tcei_lora35/data/validation.json"

MODEL_MAX_Length=2048 # if conduct multi-images sft, please set MODEL_MAX_Length=4096

DISTRIBUTED_ARGS="
    --nproc_per_node $GPUS_PER_NODE \
    --nnodes $NNODES \
    --node_rank $NODE_RANK \
    --master_addr $MASTER_ADDR \
    --master_port $MASTER_PORT
"
torchrun $DISTRIBUTED_ARGS /root/gpufree-data/tcei_lora35/tools/train_budget.py  \
    --model_name_or_path $MODEL \
    --data_path $DATA \
    --eval_data_path $EVAL_DATA \
    --remove_unused_columns false \
    --label_names "labels" \
    --prediction_loss_only true \
    --bf16 false \
    --bf16_full_eval false \
    --fp16 true \
    --fp16_full_eval true \
    --do_train \
    --do_eval \
    --tune_vision true \
    --tune_llm false \
    --use_lora true \
    --lora_target_modules "llm\..*layers\.\d+\.self_attn\.(q_proj|k_proj|v_proj|o_proj)" \
    --model_max_length $MODEL_MAX_Length \
    --max_slice_nums 9 \
    --max_steps 10000 \
    --eval_steps 1000 \
    --output_dir /root/gpufree-data/tcei_lora35/output_lora \
    --logging_dir /root/gpufree-data/tcei_lora35/tensorboard \
    --logging_strategy "steps" \
    --per_device_train_batch_size 1 \
    --per_device_eval_batch_size 1 \
    --gradient_accumulation_steps 1 \
    --evaluation_strategy "steps" \
    --save_strategy "steps" \
    --save_steps 1000 \
    --save_total_limit 2 \
    --learning_rate 1e-6 \
    --weight_decay 0.1 \
    --adam_beta2 0.95 \
    --warmup_ratio 0.01 \
    --lr_scheduler_type "cosine" \
    --logging_steps 1 \
    --gradient_checkpointing true \
    --deepspeed /root/gpufree-data/tcei_lora35/official/FM9G4B-V/finetune/ds_config_zero2.json \
    --report_to "tensorboard" \
    --load_best_model_at_end true \
    --metric_for_best_model eval_loss \
    --greater_is_better false \
    --seed 3501 
