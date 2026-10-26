"""Run the unedited official trainer with a resource cap and audit callbacks.

No architecture, optimizer or loss replacements. LoRA paths/options come from the
manual-derived launcher. The validation set alone selects the checkpoint.
"""
import atexit, fcntl, hashlib, json, os, runpy, signal, subprocess, sys, threading, time
from pathlib import Path

ROOT=Path('/root/gpufree-data/tcei_lora35')
OFFICIAL=ROOT/'official/FM9G4B-V/finetune'
if Path('/tmp/tcei_formal_trial.lock').exists(): raise RuntimeError('Formal trial active')
lock=Path('/tmp/tcei_mm35_gpu.lock').open('a+')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
apps=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader']).decode().strip()
if apps: raise RuntimeError('GPU occupied: '+apps)
import torch
import psutil
from transformers import TrainerCallback, EarlyStoppingCallback
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

# Native CUDA/DeepSpeed allocations can bypass the PyTorch allocator cap.
# Measure the whole physical GPU separately and reject a run exceeding 24GiB.
stop_monitor=threading.Event()
def monitor():
    with (ROOT/'gpu_memory.csv').open('w',buffering=1) as stream:
        stream.write('unix_time,total_gpu_used_mib,training_rss_mib\n')
        while not stop_monitor.is_set():
            try:
                used=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],timeout=5).decode().strip())
                rss=psutil.Process().memory_info().rss/1024**2
                stream.write(f'{time.time()},{used},{rss}\n')
                if used>24576:
                    (ROOT/'memory_budget_exceeded.json').write_text(json.dumps(dict(used_mib=used,limit_mib=24576,time=time.time()))+'\n')
                    os.kill(os.getpid(),signal.SIGTERM)
                    return
            except subprocess.SubprocessError:pass
            stop_monitor.wait(1)
threading.Thread(target=monitor,daemon=True).start()
atexit.register(stop_monitor.set)

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
        self.add_callback(EarlyStoppingCallback(early_stopping_patience=2,early_stopping_threshold=.005))
trainer.Trainer=AuditedTrainer
sys.argv[0]=str(OFFICIAL/'finetune.py')
runpy.run_path(str(OFFICIAL/'finetune.py'),run_name='__main__')
