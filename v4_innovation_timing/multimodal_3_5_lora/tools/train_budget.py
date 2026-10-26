"""Run the unedited official trainer with a resource cap and audit callbacks.

No architecture, optimizer or loss replacements. LoRA paths/options come from the
manual-derived launcher. The validation set alone selects the checkpoint.
"""
import atexit, fcntl, hashlib, json, os, runpy, subprocess, sys, time
from pathlib import Path

ROOT=Path('/root/gpufree-data/tcei_lora35')
OFFICIAL=ROOT/'official/FM9G4B-V/finetune'
if Path('/tmp/tcei_formal_trial.lock').exists(): raise RuntimeError('Formal trial active')
lock=Path('/tmp/tcei_mm35_gpu.lock').open('a+')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
apps=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader']).decode().strip()
if apps: raise RuntimeError('GPU occupied: '+apps)
import torch
from transformers import TrainerCallback
torch.set_num_threads(4);torch.set_num_interop_threads(1)
torch.cuda.set_per_process_memory_fraction(23*1024**3/torch.cuda.get_device_properties(0).total_memory)
started=time.time()
memory_log=(ROOT/'training_memory.jsonl').open('a',buffering=1)
def memory(event,step=None):
    r=dict(event=event,step=step,elapsed_s=time.time()-started,
        peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved())
    memory_log.write(json.dumps(r)+'\n')
    return r
atexit.register(lambda:(ROOT/'training_peak.json').write_text(json.dumps(memory('exit'),indent=2)+'\n'))

class Audit(TrainerCallback):
    def on_train_begin(self,args,state,control,model=None,**kw):
        lora=[(n,list(p.shape)) for n,p in model.named_parameters() if 'lora_' in n]
        report=dict(trainable=sum(p.numel() for p in model.parameters() if p.requires_grad),
            total=sum(p.numel() for p in model.parameters()),lora_parameters=lora,
            trainable_other=[(n,list(p.shape)) for n,p in model.named_parameters() if p.requires_grad and 'lora_' not in n],
            model_config_architectures=model.config.architectures)
        assert lora,'No LoRA target matched'
        (ROOT/'trainable_parameters.json').write_text(json.dumps(report,indent=2)+'\n')
        memory('train_begin',0)
    def on_step_end(self,args,state,control,**kw):
        memory('step',state.global_step)
        if time.time()-started>24*3600:control.should_training_stop=True
        if Path('/tmp/tcei_formal_trial.lock').exists():raise RuntimeError('New formal trial active; stop')
        return control

sys.path.insert(0,str(OFFICIAL))
import trainer
Original=trainer.Trainer
class AuditedTrainer(Original):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.add_callback(Audit())
trainer.Trainer=AuditedTrainer
sys.argv[0]=str(OFFICIAL/'finetune.py')
runpy.run_path(str(OFFICIAL/'finetune.py'),run_name='__main__')
