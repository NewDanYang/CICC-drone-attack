"""Offline full recognition-to-initial-box check on saved real RGB frames."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from v2.localizer import OverlapLocalizer,semantic_labels
from v2.geometry import local_regions,model_selected_box

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('cases',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    import cv2
    import torch
    from PIL import Image
    from transformers import AutoModel,AutoTokenizer,AutoProcessor
    cv2.setNumThreads(2);torch.set_num_threads(2);torch.set_num_interop_threads(1)
    path='/home/ubuntu/model/FM9G4B-V'
    model=AutoModel.from_pretrained(path,trust_remote_code=True,local_files_only=True,
        attn_implementation='sdpa',torch_dtype=torch.bfloat16).eval().cuda()
    tokenizer=AutoTokenizer.from_pretrained(path,trust_remote_code=True,local_files_only=True)
    raw_processor=AutoProcessor.from_pretrained(path,trust_remote_code=True,local_files_only=True)
    args.output.mkdir(parents=True,exist_ok=False)
    with (args.output/'results.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for index,case in enumerate(json.loads(args.cases.read_text())):
            evidence=[]
            class Processor:
                def __getattr__(self,name):return getattr(raw_processor,name)
                def __call__(self,prompts,images,**kwargs):
                    counts=[len(group) for group in images]
                    assert counts and all(n==1 for n in counts),counts
                    evidence.append(dict(kind='processor_input',images_per_item=counts))
                    return raw_processor(prompts,images,**kwargs)
            def infer(images,prompt):
                start=time.monotonic()
                with torch.inference_mode():
                    answers=model.chat(image=None,msgs=[[dict(role='user',content=[im,prompt])] for im in images],
                        tokenizer=tokenizer,processor=Processor(),sampling=False,stream=False,
                        num_beams=1,max_new_tokens=12,max_slice_nums=1)
                if isinstance(answers,str):answers=[answers]
                evidence.append(dict(kind='model_call',prompt=prompt,answers=answers,latency_s=time.monotonic()-start,
                    image_sizes=[im.size for im in images],image_sha256=[hashlib.sha256(im.tobytes()).hexdigest() for im in images]))
                return answers
            image=Image.open(case['image']).convert('RGB');bgr=cv2.imread(case['image'])
            start=time.monotonic()
            region=OverlapLocalizer(infer,lambda **r:evidence.append(r)).locate(image,case['color'])
            candidates,adjacency=local_regions(bgr,region)
            region_images=[Image.fromarray(cv2.cvtColor(r.pop('_pixels_bgr'),cv2.COLOR_BGR2RGB)) for r in candidates]
            labels,_=semantic_labels(region_images,infer,
                                    lambda **r:evidence.append(r)) if candidates else ([],[])
            box=model_selected_box(candidates,adjacency,labels,case['color'])
            result=dict(case,index=index,model_roi=region,candidates=candidates,adjacency=adjacency,
                        candidate_labels=labels,bbox=box,latency_s=time.monotonic()-start,
                        source_sha256=hashlib.sha256(Path(case['image']).read_bytes()).hexdigest(),evidence=evidence)
            stream.write(json.dumps(result,ensure_ascii=False)+'\n')
            print(json.dumps({k:v for k,v in result.items() if k not in ('evidence','candidates','adjacency')},ensure_ascii=False),flush=True)
    print('GRAPH_VALIDATION_DONE',flush=True)

if __name__=='__main__':main()
