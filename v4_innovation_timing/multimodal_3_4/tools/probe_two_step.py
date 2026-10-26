"""Finite OFFLINE FM9G probe. No ROS, simulator queries or deployment writes.

The detector only receives image and requested color. Labels are joined AFTER
all predictions, never used to select region/crop/box or repair model output.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import time

BBOX_PROMPT=(
    '请定位这张图片中实际可见的红色气球球体，排除小车、绳子、墙面。'
    '只输出一个JSON对象，只有bbox字段。bbox是气球可见部分的紧致矩形，'
    '格式为[x_min,y_min,x_max,y_max]，以当前这张图片的左上角为(0,0)、右下角为(1000,1000)，'
    '四个坐标均为0到1000之间的整数，x向右增加，y向下增加。'
    '没有实际可见红色气球时输出{"bbox":null}。不要解释，不要Markdown。')


def strict_json(answer):
    text=str(answer).strip();lines=text.splitlines()
    if len(lines)>=3 and lines[0].lower() in ('```json','```') and lines[-1]=='```':text='\n'.join(lines[1:-1])
    return json.loads(text)


def parse_bbox(answer,roi):
    obj=strict_json(answer)
    if not isinstance(obj,dict) or set(obj)!={'bbox'}:raise ValueError('bbox schema')
    box=obj['bbox']
    if box is None:return None
    if (not isinstance(box,list) or len(box)!=4 or any(type(v)is not int for v in box) or
        not 0<=box[0]<box[2]<=1000 or not 0<=box[1]<box[3]<=1000):raise ValueError('bbox values')
    x1,y1,x2,y2=roi;w=x2-x1;h=y2-y1
    return [x1+box[0]*w/1000,y1+box[1]*h/1000,x1+box[2]*w/1000,y1+box[3]*h/1000]


def estimate(image,target,infer,validate_full):
    result=dict(full_raw=None,full_valid=False,coarse_target=False,coarse_region=None,roi=None,bbox_raw=None,bbox=None,
        error=None,full_latency_s=None,bbox_latency_s=None)
    try:
        answer,elapsed=infer(image,'full')
        result.update(full_raw=answer,full_latency_s=elapsed)
        _,rows=validate_full(answer);result['full_valid']=True
        desired=[r for r in rows if r['color']==target]
        result['coarse_target']=bool(desired)
        if not desired:return result
        if len(desired)!=1:raise ValueError('Ambiguous multiple target records')
        region=desired[0]['region'];w,h=image.size
        roi={'left':[0,0,round(w*2/3),h],'center':[round(w/6),0,round(w*5/6),h],
             'right':[round(w/3),0,w,h]}[region]
        result.update(coarse_region=region,roi=roi)
        answer,elapsed=infer(image.crop(roi),'bbox')
        result.update(bbox_raw=answer,bbox_latency_s=elapsed,bbox=parse_bbox(answer,roi))
    except (ValueError,KeyError,TypeError) as exc:result['error']=type(exc).__name__+': '+str(exc)
    return result


def compare(box,truth):
    if box is None or truth is None:return None
    a,b,c,d=box;x,y,z,w=truth
    overlap=max(0,min(c,z)-max(a,x))*max(0,min(d,w)-max(b,y))
    union=(c-a)*(d-b)+(z-x)*(w-y)-overlap
    error=math.hypot((a+c-x-z)/2,(b+d-y-w)/2)
    threshold=max(8,.2*math.hypot(z-x,w-y))
    return dict(iou=overlap/union,center_error_px=error,center_error_threshold_px=threshold,
        passes_geometry=overlap/union>=.5 and error<=threshold)


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',type=Path,default=Path('/home/ubuntu/model/FM9G4B-V'));args=p.parse_args()
    if args.output.exists():raise RuntimeError('Refuse to overwrite a probe')
    if Path('/tmp/tcei_formal_trial.lock').exists():raise RuntimeError('Formal trial active')
    lock=Path('/tmp/tcei_mm34_gpu_offline.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);lock.seek(0);lock.truncate();lock.write(str(os.getpid()));lock.flush()
    cases=json.loads((args.data/'cases.json').read_text())
    assert len(cases)==24 and len({r['decision'] for r in cases})==24
    for row in cases:assert hashlib.sha256((args.data/row['image']).read_bytes()).hexdigest()==row['source_sha256']
    spec=importlib.util.spec_from_file_location('reference',args.reference)
    reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
    import torch
    from PIL import Image
    from transformers import AutoModel,AutoTokenizer,AutoProcessor
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    args.output.mkdir(parents=True);(args.output/'inputs').mkdir()
    log=(args.output/'calls.jsonl').open('w',encoding='utf-8',buffering=1)
    context={}
    def audit(**fields):
        log.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),**context,**fields),ensure_ascii=False)+'\n')
    class Processor:
        def __init__(self,wrapped):self.wrapped=wrapped
        def __getattr__(self,name):return getattr(self.wrapped,name)
        def __call__(self,prompts,images,**kwargs):
            counts=[len(group) for group in images]
            if not counts or any(v!=1 for v in counts):raise RuntimeError('Image contract failed')
            audit(kind='processor_input',images_per_item=counts)
            return self.wrapped(prompts,images,**kwargs)
    config=dict(model=str(args.model),reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        model_source_md5=hashlib.md5((args.model/'modeling_fm9gv.py').read_bytes()).hexdigest(),
        model_config_sha256=hashlib.sha256((args.model/'config.json').read_bytes()).hexdigest(),
        full_prompt=reference.PROMPT,full_prompt_sha256=hashlib.sha256(reference.PROMPT.encode()).hexdigest(),
        bbox_prompt=BBOX_PROMPT,max_new_tokens=128,sampling=False,num_beams=1,max_slice_nums='model processor default',
        dtype='bfloat16',gpu=torch.cuda.get_device_name(),torch_threads=torch.get_num_threads(),
        cases_sha256=hashlib.sha256((args.data/'cases.json').read_bytes()).hexdigest(),warmup_calls=1,
        estimator_inputs='only image and requested color; labels used after predictions for scoring',
        timing='synchronized model.chat including preprocessing, excluding model load and disk image writes')
    (args.output/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    tok=AutoTokenizer.from_pretrained(str(args.model),trust_remote_code=True,local_files_only=True)
    proc=Processor(AutoProcessor.from_pretrained(str(args.model),trust_remote_code=True,local_files_only=True))
    model=AutoModel.from_pretrained(str(args.model),trust_remote_code=True,local_files_only=True,
        torch_dtype=torch.bfloat16).cuda().to(dtype=torch.bfloat16).eval()
    print('MODEL_READY instance='+str(id(model)),flush=True)
    def infer(image,stage):
        context['stage']=stage
        destination=args.output/'inputs'/(context['decision']+'_'+stage+'.png');image.save(destination)
        prompt=reference.PROMPT if stage=='full' else BBOX_PROMPT
        audit(kind='source',image=destination.relative_to(args.output).as_posix(),size=image.size,
            sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
        torch.cuda.synchronize();start=time.perf_counter()
        with torch.inference_mode():
            answer=model.chat(image=None,msgs=[{'role':'user','content':[image,prompt]}],
                tokenizer=tok,processor=proc,sampling=False,stream=False,num_beams=1,max_new_tokens=128)
        torch.cuda.synchronize();elapsed=time.perf_counter()-start
        if not isinstance(answer,str):raise RuntimeError('Unexpected answer type '+type(answer).__name__)
        audit(kind='answer',answer=answer,latency_s=elapsed,model_instance=id(model))
        return answer,elapsed
    context.update(decision='warmup',warmup=True)
    with Image.open(args.data/cases[0]['image']) as source:infer(source.convert('RGB'),'full')
    predictions=[]
    with (args.output/'predictions.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for i,row in enumerate(cases,1):
            if Path('/tmp/tcei_formal_trial.lock').exists():raise RuntimeError('New formal trial started; abort offline probe')
            context.clear();context.update(decision=row['decision'],warmup=False)
            with Image.open(args.data/row['image']) as source:
                prediction=estimate(source.convert('RGB'),'red',infer,reference.validate)
            result=dict(decision=row['decision'],source_sha256=row['source_sha256'],**prediction)
            stream.write(json.dumps(result,ensure_ascii=False)+'\n');predictions.append(result)
            print(f"{i}/24 {row['decision']} coarse={result['coarse_target']} bbox={result['bbox']} error={result['error']}",flush=True)
    # Ground truth is first consulted here, after all raw detector outputs exist.
    labels={r['decision']:r for r in cases}
    scored=[]
    for row in predictions:
        label=labels[row['decision']]
        scored.append(dict(row,visibility=label['visibility'],original_frame_clipped=label['original_frame_clipped'],
            geometry=compare(row['bbox'],label['visible_bbox'])))
    (args.output/'scored.json').write_text(json.dumps(scored,ensure_ascii=False,indent=2)+'\n')
    visible=[r for r in scored if r['visibility']=='visible'];absent=[r for r in scored if r['visibility']=='not_visible']
    summary=dict(n=len(scored),visible=len(visible),absent=len(absent),uncertain=len(scored)-len(visible)-len(absent),
        coarse_visible_hits=sum(r['coarse_target'] for r in visible),nonempty_visible_boxes=sum(r['bbox'] is not None for r in visible),
        usable_visible_boxes=sum(bool(r['geometry'] and r['geometry']['passes_geometry']) for r in visible),
        false_positive_boxes_on_absent=sum(r['bbox'] is not None for r in absent),
        schema_or_parse_errors=sum(r['error'] is not None for r in scored))
    summary['passes_preflight_probe_gate']=(summary['coarse_visible_hits']==8 and summary['usable_visible_boxes']>=6 and summary['false_positive_boxes_on_absent']==0)
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
