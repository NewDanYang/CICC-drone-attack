"""Archive logs/configuration/predictions after the pair; never package model weights."""
import hashlib, importlib.metadata, json, tarfile
from pathlib import Path

root=Path('/root/gpufree-data/tcei_lora35')
assert (root/'evaluation_complete.json').exists(),'Pair is incomplete'
dest=root/'final_run.tar.gz'
if dest.exists():raise RuntimeError('Refuse overwrite')
versions={p:importlib.metadata.version(p) for p in ['torch','transformers','peft','deepspeed','accelerate','numpy','torchvision','safetensors']}
(root/'training_environment.json').write_text(json.dumps(versions,indent=2)+'\n')
names=['training_attempt4.log','training_process.json','training_wall_budget.json','training_receipt.json',
    'trainable_parameters.json','gpu_memory.csv','training_memory.jsonl','training_peak.json',
    'checkpoint200_update_proof.json','evaluation_process.json','evaluation_complete.json','paired_runner.log',
    'base_test.log','adapter_test.log','runtime_after.json','runtime_integrity_comparison.json',
    'base_weights_after.sha256','base_weights_before.sha256','training_environment.json',
    'output_lora/trainer_state.json','output_lora/checkpoint-800/trainer_state.json',
    'output_lora/checkpoint-800/adapter_config.json','output_lora/checkpoint-800/experiment_complete.json']
for directory in ['tools','configs','base_test','adapter_test','paired_analysis']:
    names.extend(str(p.relative_to(root)) for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
manifest={}
for name in sorted(set(names)):
    path=root/name
    assert path.resolve().is_relative_to(root.resolve()) and path.is_file(),name
    assert path.stat().st_size<20*1024**2,'Unexpected large file: '+name
    manifest[name]=dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
(root/'final_run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
with tarfile.open(dest,'w:gz') as archive:
    for name in list(manifest)+['final_run_manifest.json']:archive.add(root/name,arcname=name,recursive=False)
print(json.dumps(dict(path=str(dest),bytes=dest.stat().st_size,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),files=len(manifest))))
