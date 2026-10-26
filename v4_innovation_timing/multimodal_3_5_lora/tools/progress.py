"""Compact, read-only training snapshot. No model load or environment dump."""
import ast,json,time,shutil
from pathlib import Path
root=Path('/root/gpufree-data/tcei_lora35')
def tail(path,n=65536):
    if not path.exists():return ''
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-n));return f.read().decode('utf-8','replace')
steps=[]
for line in tail(root/'training_memory.jsonl').splitlines():
    try:
        r=json.loads(line)
        if r['event']=='step':steps.append(r)
    except (ValueError,KeyError):pass
losses=[]
for line in tail(root/'training_attempt3.log',262144).replace('\r','\n').splitlines():
    if line.startswith("{'loss':"):
        try:losses.append(ast.literal_eval(line))
        except (ValueError,SyntaxError):pass
gpu=tail(root/'gpu_memory.csv',1024).splitlines()[-1:]
print(json.dumps(dict(now=time.time(),last_step=steps[-1] if steps else None,last_loss=losses[-1] if losses else None,
    gpu_csv_last=gpu,free_disk_gib=shutil.disk_usage(root).free/1024**3,
    checkpoints=[p.name for p in (root/'output_lora').glob('checkpoint-*')],
    fatal_tail='Traceback' in tail(root/'training_attempt3.log',8192)),ensure_ascii=False))
