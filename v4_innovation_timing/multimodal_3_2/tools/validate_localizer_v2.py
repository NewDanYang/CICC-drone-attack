"""Offline real-frame localizer validation. Does not import ROS."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from v2.localizer import TiledLocalizer
from probe_tiled_batch_v2 import ProcessorAudit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('cases',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--levels',type=int,default=3)
    args=parser.parse_args()
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoTokenizer, AutoProcessor
    path='/home/ubuntu/model/FM9G4B-V'
    tokenizer=AutoTokenizer.from_pretrained(path,trust_remote_code=True,local_files_only=True)
    processor=ProcessorAudit(AutoProcessor.from_pretrained(path,trust_remote_code=True,local_files_only=True))
    model=AutoModel.from_pretrained(path,trust_remote_code=True,local_files_only=True,
        attn_implementation='sdpa',torch_dtype=torch.bfloat16).eval().cuda()
    args.output.mkdir(parents=True,exist_ok=False)
    with (args.output/'results.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for index,case in enumerate(json.loads(args.cases.read_text(encoding='utf-8'))):
            evidence=[]
            def infer(images,prompt):
                start=time.monotonic()
                with torch.inference_mode():
                    answers=model.chat(image=None,msgs=[[{'role':'user','content':[im,prompt]}] for im in images],
                        tokenizer=tokenizer,processor=processor,sampling=False,stream=False,num_beams=1,
                        max_new_tokens=64 if len(images)==1 else 12,max_slice_nums=1)
                if isinstance(answers,str): answers=[answers]
                evidence.append({'kind':'inference','batch_size':len(images),
                    'processor_images':processor.calls[-1],'latency_s':time.monotonic()-start,
                    'answers':answers,'prompt':prompt})
                return answers
            image=Image.open(case['image']).convert('RGB')
            start=time.monotonic()
            error=None
            try:
                box=TiledLocalizer(infer,lambda **kwargs: evidence.append(kwargs)).locate(image,case['color'],levels=case.get('levels',args.levels))
            except Exception as exc:
                error=repr(exc)
                box=None
            result=dict(case,index=index,bbox=box,error=error,latency_s=time.monotonic()-start,
                image_sha256=hashlib.sha256(Path(case['image']).read_bytes()).hexdigest(),evidence=evidence)
            stream.write(json.dumps(result,ensure_ascii=False)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k!='evidence'},ensure_ascii=False),flush=True)
    print('VALIDATION_DONE',flush=True)


if __name__=='__main__':
    main()
