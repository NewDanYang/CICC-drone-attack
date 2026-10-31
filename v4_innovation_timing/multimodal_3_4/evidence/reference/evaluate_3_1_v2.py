"""Offline FM9G development-set reevaluation. No ROS or control publishing."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

PROMPT = (
    '请逐一列出图中实际可见的气球，包括部分遮挡和画面边缘的气球。'
    '不要把小车、标牌或墙当成气球，不推测完全遮挡的气球。'
    '只输出一个JSON对象，顶层只有balloons数组；没有可见气球时输出 {"balloons":[]}。'
    '数组中每个气球用一个对象表示，对象只有color和region两个字段。'
    'color必须是一个单独的字符串，从以下四个值中选择一个：red、blue、purple、unknown。'
    '红色填red，蓝色填blue，紫色填purple；无法确定颜色时填unknown。'
    '禁止将多个颜色拼在一起，禁止使用竖线或斜杠。'
    'region按气球可见部分中心所在的图像宽度三等分区域填写，'
    '只能选择一个值：left、center、right。不要输出解释或Markdown。'
)
COLORS = {'red', 'blue', 'purple', 'unknown'}
REGIONS = {'left', 'center', 'right'}


def validate(answer):
    if isinstance(answer, (tuple, list)) and answer:
        answer = answer[0]
    raw = answer if isinstance(answer, str) else str(answer)
    text = raw.strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].lower() in ('```json', '```') and lines[-1] == '```':
        text = '\n'.join(lines[1:-1])
    obj = json.loads(text)
    if not isinstance(obj, dict) or set(obj) != {'balloons'}:
        raise ValueError('top-level must contain only balloons')
    if not isinstance(obj['balloons'], list):
        raise ValueError('balloons must be an array')
    for item in obj['balloons']:
        if not isinstance(item, dict) or set(item) != {'color', 'region'}:
            raise ValueError('each balloon must contain only color and region')
        if not isinstance(item['color'], str) or item['color'] not in COLORS:
            raise ValueError('invalid color: ' + repr(item['color']))
        if not isinstance(item['region'], str) or item['region'] not in REGIONS:
            raise ValueError('invalid region: ' + repr(item['region']))
    return raw, obj['balloons']


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p / 100
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def score(rows):
    result = {'frames': len(rows), 'per_collection_group': {}}
    for group in ('red', 'blue', 'purple'):
        part = [r for r in rows if r['collection_group'] == group]
        visible = [r for r in part if r['target_visibility'] == 'visible']
        absent = [r for r in part if r['target_visibility'] == 'not_visible']
        result['per_collection_group'][group] = {
            'frames': len(part),
            'visible_target_frames': len(visible),
            'visible_target_hits': sum(r['target_hit'] is True for r in visible),
            'visible_target_hit_rate': sum(r['target_hit'] is True for r in visible) / len(visible) if visible else None,
            'uncertain_target_frames': sum(r['target_visibility'] == 'uncertain' for r in part),
            'not_visible_frames': len(absent),
            'false_target_predictions_on_not_visible': sum(group in r['predicted_colors'] for r in absent if r['schema_valid']),
            'schema_invalid': sum(not r['schema_valid'] and not r['inference_error'] for r in part),
            'inference_errors': sum(bool(r['inference_error']) for r in part),
            'successful_call_p50_s': pct([r['latency_s'] for r in part if not r['inference_error']], 50),
            'successful_call_p95_s': pct([r['latency_s'] for r in part if not r['inference_error']], 95),
        }
    certain = [r for r in rows if r['target_visibility'] != 'uncertain']
    result.update({
        'color_set_exact_frames': len(certain),
        'color_set_exact_correct': sum(r['color_set_exact'] is True for r in certain),
        'color_set_exact_accuracy': sum(r['color_set_exact'] is True for r in certain) / len(certain) if certain else None,
        'schema_invalid': sum(not r['schema_valid'] and not r['inference_error'] for r in rows),
        'inference_errors': sum(bool(r['inference_error']) for r in rows),
        'unknown_response_count': sum(r['unknown_count'] > 0 for r in rows),
        'successful_call_p50_s': pct([r['latency_s'] for r in rows if not r['inference_error']], 50),
        'successful_call_p95_s': pct([r['latency_s'] for r in rows if not r['inference_error']], 95),
        'timing_scope': 'image decode + synchronous GPU model.chat; parsing excluded; model load and optional warmup excluded',
        'region_accuracy': None,
        'region_note': 'Schema validated only; no independent region ground truth.',
        'result_scope': 'Development-set prompt reevaluation with provisional visibility labels; not independent acceptance.',
    })
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('/home/ubuntu/multimodal_task3/eval_frames_gated'))
    parser.add_argument('--model', type=Path, default=Path('/home/ubuntu/model/FM9G4B-V'))
    parser.add_argument('--output-root', type=Path, default=Path('/home/ubuntu/multimodal_task3'))
    parser.add_argument('--labels', type=Path, default=Path(__file__).with_name('labels.jsonl'))
    parser.add_argument('--run', action='store_true', help='Explicitly load model and run; default only checks data')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='Use first frame of each collection group')
    parser.add_argument('--warmup', type=int, default=1)
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error('warmup cannot be negative')
    labels = [json.loads(s) for s in args.labels.read_text(encoding='utf-8').splitlines() if s.strip()]
    if len(labels) != 60 or len({r['image'] for r in labels}) != 60:
        raise SystemExit('Expected 60 unique labeled images')
    if Counter(r['collection_group'] for r in labels) != {'red': 20, 'blue': 20, 'purple': 20}:
        raise SystemExit('Expected 20 frames in each collection group')
    for item in labels:
        path = args.data / item['image']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise SystemExit('Image differs from reviewed original: ' + str(path))
    print('DATA_OK: all 60 image hashes match the reviewed originals', flush=True)
    for group in ('red', 'blue', 'purple'):
        print(group, dict(Counter(r['target_visibility'] for r in labels if r['collection_group'] == group)), flush=True)
    print('Labels are provisional; blue has only 14 independently identifiable target frames.', flush=True)
    if args.check or not args.run:
        return
    if args.smoke:
        labels = [next(r for r in labels if r['collection_group'] == c) for c in ('red', 'blue', 'purple')]

    import torch
    from PIL import Image
    from transformers import AutoModel, AutoTokenizer, AutoProcessor
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise SystemExit('This configuration requires a BF16-capable CUDA GPU, matching the successful baseline.')
    out = args.output_root / ('eval_3_1_v2_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    config = {'prompt': PROMPT, 'model': str(args.model), 'data': str(args.data),
              'sampling': False, 'max_new_tokens': 128, 'dtype': 'bfloat16',
              'output_normalization': 'Accept one complete JSON Markdown fence; preserve raw; strict schema validation',
              'warmup_calls': args.warmup, 'smoke': args.smoke,
              'torch_version': torch.__version__, 'gpu': torch.cuda.get_device_name(),
              'image_input': 'original full 640x480 RGB; no crops or resizing before chat',
              'labels_sha256': hashlib.sha256(args.labels.read_bytes()).hexdigest()}
    (out / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'labels.jsonl').write_bytes(args.labels.read_bytes())
    print('Result directory:', out, flush=True)
    print('Loading one offline model instance...', flush=True)
    tok = AutoTokenizer.from_pretrained(str(args.model), trust_remote_code=True, local_files_only=True)
    proc = AutoProcessor.from_pretrained(str(args.model), trust_remote_code=True, local_files_only=True)
    model = AutoModel.from_pretrained(str(args.model), trust_remote_code=True, local_files_only=True,
                                      torch_dtype=torch.bfloat16).cuda().to(dtype=torch.bfloat16).eval()

    def infer(item):
        torch.cuda.synchronize()
        started = time.perf_counter()
        with Image.open(args.data / item['image']) as src:
            im = src.convert('RGB')
        try:
            with torch.inference_mode():
                answer = model.chat(image=im, msgs=[{'role': 'user', 'content': PROMPT}],
                                    tokenizer=tok, processor=proc, sampling=False, stream=False,
                                    num_beams=1, max_new_tokens=128)
            torch.cuda.synchronize()
        finally:
            im.close()
        return answer, time.perf_counter() - started

    for _ in range(args.warmup):
        infer(labels[0])
    rows = []
    with (out / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
        for index, item in enumerate(labels, 1):
            row = dict(item, raw='', predicted_colors=[], schema_valid=False, unknown_count=0,
                       inference_error=None, schema_error=None, target_hit=False,
                       color_set_exact=False, latency_s=None)
            started = time.perf_counter()
            try:
                answer, row['latency_s'] = infer(item)
            except Exception as exc:
                row['latency_s'] = time.perf_counter() - started
                row['inference_error'] = type(exc).__name__ + ': ' + str(exc)
            else:
                row['raw'] = answer if isinstance(answer, str) else str(answer[0] if isinstance(answer, (tuple, list)) and answer else answer)
                try:
                    _, balloons = validate(answer)
                    row['schema_valid'] = True
                    row['predicted_colors'] = sorted({b['color'] for b in balloons if b['color'] != 'unknown'})
                    row['unknown_count'] = sum(b['color'] == 'unknown' for b in balloons)
                    row['target_hit'] = item['collection_group'] in row['predicted_colors']
                    row['color_set_exact'] = (row['predicted_colors'] == item['visible_colors'] and row['unknown_count'] == 0)
                except Exception as exc:
                    row['schema_error'] = type(exc).__name__ + ': ' + str(exc)
            if item['target_visibility'] != 'visible':
                row['target_hit'] = None
            if item['target_visibility'] == 'uncertain':
                row['color_set_exact'] = None
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            rows.append(row)
            print(f"{index}/{len(labels)} {item['image']} valid={row['schema_valid']} colors={row['predicted_colors']} time={row['latency_s']:.3f}s", flush=True)
            if row['inference_error']:
                print(row['inference_error'], flush=True)
                if sum(bool(r['inference_error']) for r in rows[-3:]) == 3:
                    print('Stopping after three consecutive inference errors.', flush=True)
                    break
    summary = score(rows)
    summary.update({'complete': len(rows) == len(labels), 'smoke': args.smoke,
                    'scheduled_frames': len(labels), 'warmup_calls': args.warmup})
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print('Result directory:', out, flush=True)


if __name__ == '__main__':
    main()
