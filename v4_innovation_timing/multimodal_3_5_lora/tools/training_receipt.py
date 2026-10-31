"""Record the validation-selected artifact and measured resources after training."""
import argparse, csv, hashlib, json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/root/gpufree-data/tcei_lora35'))
a=p.parse_args();root=a.root;out=root/'training_receipt.json'
if out.exists():raise RuntimeError('Refuse overwrite')
state=json.loads((root/'output_lora/trainer_state.json').read_text())
chosen=Path(state['best_model_checkpoint']);marker=json.loads((chosen/'experiment_complete.json').read_text())
assert marker['cases_sha256']==hashlib.sha256((root/'data/cases.json').read_bytes()).hexdigest()
def digest(path):
    h=hashlib.sha256();m=hashlib.md5()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block);m.update(block)
    return dict(bytes=path.stat().st_size,sha256=h.hexdigest(),md5=m.hexdigest())
names=['adapter_config.json','adapter_model.safetensors','trainer_state.json','experiment_complete.json']
artifacts={str(chosen/n):digest(chosen/n) for n in names}
final=root/'output_lora/adapter_model.safetensors'
if final.exists():artifacts[str(final)]=digest(final)
with (root/'gpu_memory.csv').open() as f:resources=list(csv.DictReader(f))
record=dict(final_step=state['global_step'],selected_step=marker['global_step'],
    selected_checkpoint=str(chosen),best_validation_loss=state['best_metric'],
    validation_curve=[x for x in state['log_history'] if 'eval_loss' in x],
    final_metrics=[x for x in state['log_history'] if 'train_runtime' in x],
    peak_total_gpu_mib=max(int(r['total_gpu_used_mib']) for r in resources),
    peak_training_rss_mib=max(float(r['training_rss_mib']) for r in resources),
    monitored_seconds=float(resources[-1]['unix_time'])-float(resources[0]['unix_time']),
    torch_peak=json.loads((root/'training_peak.json').read_text()),
    training_budget=json.loads((root/'training_wall_budget.json').read_text()),artifacts=artifacts)
assert record['peak_total_gpu_mib']<=24576
out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
