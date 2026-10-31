"""Run the official FM9G4B-V trainer with a corrected, auditable LoRA surface.

The official trainer is reused for the data pipeline and loss. This wrapper only
forces the 3.8 audit choices: no modules_to_save, no vision tuning, and no
non-LoRA trainable parameters. The target-module regex is supplied by the
launcher so each learning-rate run records it in the command log.
"""
import atexit
import fcntl
import hashlib
import json
import os
import runpy
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("MM38_RUN_ROOT", "/root/gpufree-data/mm38_config_fix/lr_1e-4"))
OFFICIAL = Path("/root/gpufree-data/mm36_lora_v2/official/FM9G4B-V/finetune")
ROOT.mkdir(parents=True, exist_ok=True)
budget_path = ROOT / "training_wall_budget.json"
if not budget_path.exists():
    budget_path.write_text(json.dumps({"first_effective_training_start": time.time(),
                                       "deadline": time.time() + 48 * 3600}) + "\n")
deadline = json.loads(budget_path.read_text())["deadline"]
if time.time() >= deadline:
    raise RuntimeError("48h training wall budget exhausted")
if Path("/tmp/tcei_formal_trial.lock").exists():
    raise RuntimeError("Formal trial active")
lock = Path("/tmp/tcei_mm38_gpu.lock").open("a+")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
apps = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"]).decode().strip()
if apps:
    raise RuntimeError("GPU occupied: " + apps)

import torch
import psutil
from transformers import TrainerCallback

torch.set_num_threads(4)
torch.set_num_interop_threads(1)
torch.cuda.set_per_process_memory_fraction(23 * 1024**3 / torch.cuda.get_device_properties(0).total_memory)
started = time.time()
memory_log = (ROOT / "training_memory.jsonl").open("a", buffering=1)


def memory(event, step=None):
    r = dict(event=event, step=step, elapsed_s=time.time() - started,
             peak_allocated_bytes=torch.cuda.max_memory_allocated(),
             peak_reserved_bytes=torch.cuda.max_memory_reserved())
    memory_log.write(json.dumps(r) + "\n")
    return r


atexit.register(lambda: (ROOT / "training_peak.json").write_text(json.dumps(memory("exit"), indent=2) + "\n"))
stop_monitor = threading.Event()


def monitor():
    with (ROOT / "gpu_memory.csv").open("w", buffering=1) as stream:
        stream.write("unix_time,total_gpu_used_mib,training_rss_mib\n")
        while not stop_monitor.is_set():
            try:
                used = int(subprocess.check_output([
                    "nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"
                ], timeout=5).decode().strip())
                rss = psutil.Process().memory_info().rss / 1024**2
                stream.write(f"{time.time()},{used},{rss}\n")
                if used > 24576:
                    (ROOT / "memory_budget_exceeded.json").write_text(json.dumps(
                        {"used_mib": used, "limit_mib": 24576, "time": time.time()}) + "\n")
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
            except subprocess.SubprocessError:
                pass
            stop_monitor.wait(1)


threading.Thread(target=monitor, daemon=True).start()
atexit.register(stop_monitor.set)


class Audit(TrainerCallback):
    def on_train_begin(self, args, state, control, model=None, **kw):
        lora = [(n, list(p.shape)) for n, p in model.named_parameters() if "lora_" in n]
        other = [(n, list(p.shape)) for n, p in model.named_parameters()
                 if p.requires_grad and "lora_" not in n]
        report = dict(
            trainable=sum(p.numel() for p in model.parameters() if p.requires_grad),
            total=sum(p.numel() for p in model.parameters()),
            lora_parameters=lora,
            trainable_other=other,
            model_config_architectures=model.config.architectures,
            target_modules=os.environ.get("MM38_TARGET_MODULES"),
            learning_rate=os.environ.get("MM38_LEARNING_RATE"),
            modules_to_save_forced_none=True,
            tune_vision=False,
        )
        assert lora, "No LoRA target matched"
        assert not other, "Non-LoRA parameters remain trainable: " + repr(other[:5])
        (ROOT / "trainable_parameters.json").write_text(json.dumps(report, indent=2) + "\n")
        memory("train_begin", 0)

    def on_step_end(self, args, state, control, **kw):
        memory("step", state.global_step)
        if time.time() >= deadline:
            control.should_training_stop = True
        if Path("/tmp/tcei_formal_trial.lock").exists():
            raise RuntimeError("New formal trial active; stop")
        return control

    def on_save(self, args, state, control, **kw):
        folder = Path(args.output_dir) / f"checkpoint-{state.global_step}"
        assert folder.resolve().is_relative_to((ROOT / "output_lora").resolve())
        assert (folder / "trainer_state.json").is_file()
        assert (folder / "adapter_model.safetensors").is_file()
        assert list(folder.glob("global_step*/*optim_states.pt"))
        marker = dict(global_step=state.global_step,
                      cases_sha256=hashlib.sha256((ROOT / "data/cases.json").read_bytes()).hexdigest(),
                      completed_at=time.time())
        tmp = folder / "experiment_complete.tmp"
        tmp.write_text(json.dumps(marker) + "\n")
        tmp.replace(folder / "experiment_complete.json")


# The official finetune.py constructs LoraConfig with embed_tokens/resampler.
# Intercept that one constructor call and freeze everything except LoRA matrices.
import peft

_RealLoraConfig = peft.LoraConfig


class FixedLoraConfig(_RealLoraConfig):
    def __init__(self, *args, **kwargs):
        kwargs["modules_to_save"] = None
        super().__init__(*args, **kwargs)


peft.LoraConfig = FixedLoraConfig
_real_get_peft_model = peft.get_peft_model


def fixed_get_peft_model(model, peft_config, *args, **kwargs):
    wrapped = _real_get_peft_model(model, peft_config, *args, **kwargs)
    for name, param in wrapped.named_parameters():
        param.requires_grad = "lora_" in name
    return wrapped


peft.get_peft_model = fixed_get_peft_model
sys.path.insert(0, str(OFFICIAL))
import trainer

OriginalTrainer = trainer.Trainer


class AuditedTrainer(OriginalTrainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_callback(Audit())


trainer.Trainer = AuditedTrainer
sys.argv[0] = str(OFFICIAL / "finetune.py")
runpy.run_path(str(OFFICIAL / "finetune.py"), run_name="__main__")
