"""Make budget/path-only changes to the launcher extracted from the manual."""
from pathlib import Path
import difflib,json,hashlib,tarfile
BASE=Path(__file__).resolve().parents[1]
original=(BASE/'evidence/reference/finetune_lora.manual.sh').read_text(encoding='utf-8')
root='/root/gpufree-data/tcei_lora35'
replacements={
    'MODEL="xxxx/FM9G4B-V"':'MODEL="/home/ubuntu/model/FM9G4B-V"',
    '\nDATA="FM9G4B-V/finetune/data.json"':f'\nDATA="{root}/data/train.json"',
    'EVAL_DATA="FM9G4B-V/finetune/data.json"':f'EVAL_DATA="{root}/data/validation.json"',
    'finetune.py':f'{root}/tools/train_budget.py',
    '--prediction_loss_only false':'--prediction_loss_only true',
    '--bf16 false':'--bf16 true',
    '--bf16_full_eval false':'--bf16_full_eval true',
    '--fp16 true':'--fp16 false',
    '--fp16_full_eval true':'--fp16_full_eval false',
    '--eval_steps 1000':'--eval_steps 200',
    '--save_steps 1000':'--save_steps 200',
    '--save_total_limit 10':'--save_total_limit 2',
    'output/output__lora':f'{root}/output_lora',
    'output/output_lora':f'{root}/tensorboard',
    '--deepspeed ds_config_zero2.json':f'--deepspeed {root}/configs/ds_config_zero2_cpu.json',
    '--report_to "tensorboard"':' \\\n'.join(['--report_to "tensorboard"', '    --load_best_model_at_end true', '    --metric_for_best_model eval_loss', '    --greater_is_better false', '    --seed 3501']),
}
changed=original
for a,b in replacements.items():
    assert changed.count(a)==1,(a,changed.count(a))
    changed=changed.replace(a,b)
changed=changed.replace('#!/bin/bash\n','#!/bin/bash\nset -euo pipefail\nexport PATH="'+root+'/venv/bin:$PATH"\nexport OMP_NUM_THREADS=4\nexport TOKENIZERS_PARALLELISM=false\nexport HF_HUB_OFFLINE=1\nexport TRANSFORMERS_OFFLINE=1\nexport TORCH_EXTENSIONS_DIR="'+root+'/torch_extensions"\nexport MAX_JOBS=4\n')
dest=BASE/'tools/finetune_lora.sh';dest.write_text(changed,encoding='utf-8',newline='\n')
(BASE/'evidence/reference/launcher.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),fromfile='manual',tofile='budget_launcher')),encoding='utf-8')
print('launcher',hashlib.sha256(dest.read_bytes()).hexdigest())
with tarfile.open(BASE/'evidence/reference/official_training.tar.gz') as tar:
    original_config=tar.extractfile('FM9G4B-V/finetune/ds_config_zero2.json').read().decode()
config=json.loads(original_config)
config['zero_optimization']['offload_optimizer']['device']='cpu'
# Retain the official trainer's torch AdamW algorithm when moving states to CPU.
config['zero_force_ds_cpu_optimizer']=False
(BASE/'configs').mkdir(exist_ok=True)
changed_config=json.dumps(config,indent=2)+'\n'
(BASE/'configs/ds_config_zero2_cpu.json').write_text(changed_config,encoding='utf-8',newline='\n')
(BASE/'evidence/reference/deepspeed_cpu.diff').write_text(''.join(difflib.unified_diff(original_config.splitlines(True),changed_config.splitlines(True),fromfile='official_zero2',tofile='cpu_optimizer_zero2')),encoding='utf-8')
