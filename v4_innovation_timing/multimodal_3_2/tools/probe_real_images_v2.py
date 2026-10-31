"""Real-image development probe; no ROS, flight control or detector fallback."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def prompt(color):
    name = {'red': '红色', 'purple': '紫色', 'blue': '蓝色'}[color]
    return (f'在这张完整图片中定位{name}气球本身，不包括气球下面的小车。'
            '只根据图像，不要猜测被完全遮挡或画面外的气球。'
            '只输出JSON：{"visible":true,"bbox":[x1,y1,x2,y2]}。'
            'bbox为气球紧致外接矩形，左上和右下坐标；横纵坐标均按0到1000归一化。'
            '如果图中没有可辨认的指定颜色气球，输出{"visible":false,"bbox":null}。')


class AuditedProcessor:
    def __init__(self, processor):
        self.processor = processor
        self.calls = []

    def __getattr__(self, name):
        return getattr(self.processor, name)

    def __call__(self, prompts, images, **kwargs):
        counts = [len(group) for group in images]
        self.calls.append(counts)
        if counts != [1]:
            raise ValueError(f'Expected one actual processor image, got {counts}')
        return self.processor(prompts, images, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path, help='JSON array of image/color cases')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    import cv2
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoTokenizer, AutoProcessor
    path = '/home/ubuntu/model/FM9G4B-V'
    print('cv2', cv2.__version__, [n for n in dir(cv2) if n.startswith('Tracker')], flush=True)
    tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True, local_files_only=True)
    processor = AuditedProcessor(AutoProcessor.from_pretrained(path, trust_remote_code=True, local_files_only=True))
    model = AutoModel.from_pretrained(path, trust_remote_code=True, local_files_only=True,
                                     attn_implementation='sdpa', torch_dtype=torch.bfloat16).eval().cuda()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8', buffering=1) as output:
        for case in json.loads(args.input.read_text(encoding='utf-8')):
            image = Image.open(case['image']).convert('RGB')
            question = case.get('prompt', prompt(case['color']))
            start = time.monotonic()
            with torch.inference_mode():
                answer = model.chat(image=None, msgs=[{'role': 'user', 'content': [image, question]}],
                                    tokenizer=tokenizer, processor=processor, sampling=False, stream=False,
                                    num_beams=1, max_new_tokens=case.get('max_new_tokens', 100))
            torch.cuda.synchronize()
            row = dict(case, image_sha256=hashlib.sha256(Path(case['image']).read_bytes()).hexdigest(),
                       size=image.size, prompt=question, answer=str(answer),
                       processor_images=processor.calls[-1], latency_s=time.monotonic()-start)
            output.write(json.dumps(row, ensure_ascii=False)+'\n')
            print(json.dumps(row, ensure_ascii=False), flush=True)
    print('PROBE_DONE', flush=True)


if __name__ == '__main__':
    main()
