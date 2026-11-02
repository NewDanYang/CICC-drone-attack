#!/usr/bin/env python3
"""Benchmark track_sweep-equivalent model call latency for varying sweep count (N) and
resolution (RES), to see how much decision-cycle speedup is available before accuracy
degrades. Mirrors the exact batch shape presence.py's track() sends: 1 + 4*N images at
RES x RES. No flight, no sim -- pure GPU timing on dummy frames, same model instance as
deployed (FM9G4B-V, bf16).
usage: p15_latency_bench.py
"""
import json, statistics, sys, time
from pathlib import Path
import torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer
sys.path.insert(0, str(Path(__file__).parent))
from fastpresence import FastPresence

MODEL = "/home/ubuntu/model/FM9G4B-V"
tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True,
                                   torch_dtype=torch.bfloat16).cuda().eval()

TEXT = "这张图片里有没有蓝色的气球？只回答“是”或“否”。"


def timed(fp, images, text, reps=20):
    # warmup
    for _ in range(3):
        fp(images, text)
    torch.cuda.synchronize()
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fp(images, text)
        torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)
    return times


results = {}
for res in (168, 182, 196, 210, 224):
    fp = FastPresence(model, tok, proc, res=res)
    for n_track in (3, 4, 5, 6, 7):
        batch = 1 + 4 * n_track
        images = torch.randint(0, 255, (batch, res, res, 3), dtype=torch.uint8, device="cuda")
        times = timed(fp, images, TEXT)
        key = f"res{res}_n{n_track}"
        results[key] = dict(res=res, n_track=n_track, batch=batch,
                             median_s=statistics.median(times), p90_s=sorted(times)[int(len(times) * 0.9)],
                             min_s=min(times), max_s=max(times))
        print(key, results[key], flush=True)

Path("/root/gpufree-data/fm_research/p15_latency_bench.json").write_text(json.dumps(results, indent=1))
