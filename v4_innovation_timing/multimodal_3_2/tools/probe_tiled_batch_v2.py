"""Pure FM9G tiled recognition probe, same model; no external detector."""
import argparse
import hashlib
import json
from pathlib import Path
import time

PROMPT = ('请判断这张局部图片中实际可见的气球颜色。只输出一个词：red、purple、blue 或 none。'
          '红色气球回答red，紫色气球回答purple，蓝色气球回答blue。'
          '没有气球回答none。不要把小车、天空或墙壁当成气球。不要解释。')


class ProcessorAudit:
    def __init__(self, processor):
        self.processor = processor
        self.calls = []

    def __getattr__(self, name):
        return getattr(self.processor, name)

    def __call__(self, prompts, images, **kwargs):
        counts = [len(group) for group in images]
        if not counts or any(n != 1 for n in counts):
            raise ValueError(f'Expected one image per batch item: {counts}')
        self.calls.append(counts)
        return self.processor(prompts, images, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoTokenizer, AutoProcessor
    path='/home/ubuntu/model/FM9G4B-V'
    tokenizer=AutoTokenizer.from_pretrained(path, trust_remote_code=True, local_files_only=True)
    processor=ProcessorAudit(AutoProcessor.from_pretrained(path, trust_remote_code=True, local_files_only=True))
    model=AutoModel.from_pretrained(path, trust_remote_code=True, local_files_only=True,
        torch_dtype=torch.bfloat16, attn_implementation='sdpa').eval().cuda()
    with args.output.open('w',encoding='utf-8',buffering=1) as stream:
        for color in ('red','purple','blue'):
            source=Path('/tmp/mm_v2_probe')/(color+'.jpg')
            image=Image.open(source).convert('RGB')
            tiles=[]
            boxes=[]
            for row in range(4):
                for col in range(4):
                    box=(col*160,row*120,(col+1)*160,(row+1)*120)
                    tiles.append(image.crop(box))
                    boxes.append(box)
            msgs=[[{'role':'user','content':[tile,PROMPT]}] for tile in tiles]
            start=time.monotonic()
            with torch.inference_mode():
                answers=model.chat(image=None,msgs=msgs,tokenizer=tokenizer,processor=processor,
                    sampling=False,stream=False,num_beams=1,max_new_tokens=12,max_slice_nums=1)
            torch.cuda.synchronize()
            result={'color':color,'image':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'boxes':boxes,'answers':answers,'processor_images':processor.calls[-1],
                    'latency_s':time.monotonic()-start,'gpu_peak_bytes':torch.cuda.max_memory_allocated()}
            stream.write(json.dumps(result,ensure_ascii=False)+'\n')
            print(json.dumps(result,ensure_ascii=False),flush=True)
    print('BATCH_PROBE_DONE',flush=True)


if __name__=='__main__':
    main()
