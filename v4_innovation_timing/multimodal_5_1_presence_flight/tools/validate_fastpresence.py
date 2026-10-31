#!/usr/bin/env python3
"""Compare the P12e FastPresence logits with the official processor path."""
import json
import sys
import time
from pathlib import Path

import cv2
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'v2'))
from presence import FastPresence

MODEL = '/home/ubuntu/model/FM9G4B-V'
TEXT = '这张图片里有没有蓝色的气球？只回答“是”或“否”。'

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True)
proc.image_processor.scale_resolution = 224
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, local_files_only=True,
                                  torch_dtype=torch.bfloat16).cuda().eval()
fast = FastPresence(model, tok, proc, res=224)
yes = tok.encode('是', add_special_tokens=False)[-1]
no = tok.encode('否', add_special_tokens=False)[-1]


def official(images):
    prompts = [proc.tokenizer.apply_chat_template(
        [{'role':'user','content':'(<image>./</image>)\n'+TEXT}],
        tokenize=False, add_generation_prompt=True) for _ in images]
    with torch.inference_mode():
        inp = proc(prompts, [[im] for im in images], max_slice_nums=1,
                   return_tensors='pt', max_length=8192).to(model.device)
        inp.pop('image_sizes', None)
        emb, _ = model.get_vllm_embedding(inp)
        am = inp['attention_mask']
        pos = (am.long().cumsum(-1)-1).clamp(min=0)
        logits = model.llm(inputs_embeds=emb, attention_mask=am,
                           position_ids=pos).logits[:, -1].float()
        return torch.softmax(torch.stack([logits[:,yes], logits[:,no]], -1), -1)[:,0].tolist()


paths = sys.argv[1:]
if not paths:
    raise SystemExit('pass at least one real frame path')
images=[]
for path in paths:
    bgr=cv2.imread(path)
    if bgr is None: raise SystemExit('cannot read '+path)
    rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    images.append(Image.fromarray(rgb).resize((224,224),Image.Resampling.BICUBIC))
rgb=torch.stack([torch.from_numpy(__import__('numpy').array(im)) for im in images]).cuda()
t=time.perf_counter(); fast_p=fast(rgb,TEXT); fast_s=time.perf_counter()-t
t=time.perf_counter(); official_p=official(images); official_s=time.perf_counter()-t
diff=[abs(a-b) for a,b in zip(fast_p,official_p)]
out={'count':len(images),'fast':fast_p,'official':official_p,'abs_diff':diff,
     'max_abs_diff':max(diff),'fast_latency_s':fast_s,'official_latency_s':official_s}
print(json.dumps(out,ensure_ascii=False,indent=2))
if out['max_abs_diff']>0.03:
    raise SystemExit('FastPresence parity gate failed')
