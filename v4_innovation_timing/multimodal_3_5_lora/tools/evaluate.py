"""Paired offline evaluation. No ROS, detectors, truth queries, crop repairs or controller."""
import argparse, fcntl, hashlib, json, math, os, statistics, subprocess, time
from pathlib import Path
from build_dataset import prompts

def strict_json(text):
    text=text.strip()
    if text.startswith('```json') and text.endswith('```'): text=text[7:-3].strip()
    elif text.startswith('```') and text.endswith('```'): text=text[3:-3].strip()
    return json.loads(text)

def score(pred, label):
    ans=dict(id=label['id'],color=label['color'],present=label['present'],clipped=label['clipped'],
        region_correct=False,bbox_valid=False,bbox_nonempty=False,geometry_pass=False,iou=0,center_error_px=None)
    try:
        r=strict_json(pred['region']['answer'])
        assert isinstance(r,dict) and set(r)=={'color','region'}
        ans['region_correct']=r==dict(color=label['color'] if label['present'] else 'none',region=label['region'])
        ans['region_false_positive']=not label['present'] and r['color']!='none'
    except (ValueError,KeyError,AssertionError,TypeError): ans['region_parse_error']=True
    try:
        r=strict_json(pred['bbox']['answer']);assert isinstance(r,dict) and set(r)=={'bbox'}
        box=r['bbox']
        if box is None: ans['bbox_valid']=True
        else:
            assert isinstance(box,list) and len(box)==4 and all(type(v)is int for v in box)
            assert 0<=box[0]<box[2]<=1000 and 0<=box[1]<box[3]<=1000
            box=[v*(640/1000 if i%2==0 else 480/1000) for i,v in enumerate(box)]
            ans.update(bbox_valid=True,bbox_nonempty=True,predicted_bbox_px=box)
            if label['bbox']:
                a,b,c,d=box;x,y,z,w=label['bbox']
                inter=max(0,min(c,z)-max(a,x))*max(0,min(d,w)-max(b,y))
                iou=inter/((c-a)*(d-b)+(z-x)*(w-y)-inter)
                error=math.hypot((a+c-x-z)/2,(b+d-y-w)/2)
                threshold=max(8,.2*math.hypot(z-x,w-y))
                ans.update(iou=iou,center_error_px=error,center_error_threshold_px=threshold,
                    geometry_pass=iou>=.5 and error<=threshold)
    except (ValueError,KeyError,AssertionError,TypeError): ans['bbox_parse_error']=True
    return ans

def summarize(scored,predictions):
    def group(rows):
        pos=[x for x in rows if x['present']];neg=[x for x in rows if not x['present']]
        return dict(n=len(rows),positive=len(pos),negative=len(neg),region_hits=sum(x['region_correct'] for x in pos),
            geometry_hits=sum(x['geometry_pass'] for x in pos),nonempty=sum(x['bbox_nonempty'] for x in pos),
            region_negative_errors=sum(not x['region_correct'] for x in neg),
            bbox_negative_errors=sum(x['bbox_nonempty'] or not x['bbox_valid'] for x in neg),
            max_iou=max([x['iou'] for x in pos],default=None),
            median_center_error_px=statistics.median([x['center_error_px'] for x in pos if x['center_error_px'] is not None]) if any(x['center_error_px'] is not None for x in pos) else None)
    return dict(overall=group(scored),colors={c:group([r for r in scored if r['color']==c]) for c in ['red','purple','blue']},
        clipped=group([r for r in scored if r['clipped']]),unclipped=group([r for r in scored if not r['clipped']]),
        median_call_latency_s=statistics.median([x[k]['latency_s'] for x in predictions for k in ['region','bbox']]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--split',choices=['validation','test'],required=True);p.add_argument('--adapter',type=Path)
    p.add_argument('--model',default='/home/ubuntu/model/FM9G4B-V');a=p.parse_args()
    if a.output.exists():raise RuntimeError('Refusing to overwrite evaluation')
    if Path('/tmp/tcei_formal_trial.lock').exists():raise RuntimeError('Formal trial active')
    lock=Path('/tmp/tcei_mm35_gpu.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    apps=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader']).decode().strip()
    if apps:raise RuntimeError('GPU already has compute process: '+apps)
    import torch
    from PIL import Image
    from transformers import AutoModel,AutoTokenizer,AutoProcessor
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(23*1024**3/torch.cuda.get_device_properties(0).total_memory)
    a.output.mkdir(parents=True)
    raw=json.loads((a.data/'cases.json').read_text());labels={r['id']:r for r in raw if r['split']==a.split}
    # Estimator receives only image, requested color and identity. Truth joined after every prediction is saved.
    inputs=[{k:r[k] for k in ['id','image','sha256','color']} for r in labels.values()]
    tok=AutoTokenizer.from_pretrained(a.model,trust_remote_code=True,local_files_only=True)
    proc=AutoProcessor.from_pretrained(a.model,trust_remote_code=True,local_files_only=True)
    model=AutoModel.from_pretrained(a.model,trust_remote_code=True,local_files_only=True,torch_dtype=torch.bfloat16)
    if a.adapter:
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,str(a.adapter),is_trainable=False)
    model=model.cuda().to(dtype=torch.bfloat16).eval()
    processor_count=[0]
    class Audited:
        def __getattr__(self,k):return getattr(proc,k)
        def __call__(self,text,images,**kw):
            assert [len(g) for g in images]==[1],'No actual image in model input'
            processor_count[0]+=1
            return proc(text,images,**kw)
    processor=Audited()
    (a.output/'config.json').write_text(json.dumps(dict(model=a.model,adapter=str(a.adapter),split=a.split,
        cases_sha256=hashlib.sha256((a.data/'cases.json').read_bytes()).hexdigest(),max_new_tokens=128,
        sampling=False,num_beams=1,dtype='bfloat16',slice_nums='default=9',model_instance=id(model)),indent=2)+'\n')
    results=[]
    with (a.output/'predictions.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for i,row in enumerate(inputs,1):
            if Path('/tmp/tcei_formal_trial.lock').exists():raise RuntimeError('New formal trial active')
            path=a.data/row['image'];assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
            im=Image.open(path).convert('RGB');result=dict(row)
            for task,prompt in prompts(row['color']).items():
                torch.cuda.synchronize();start=time.perf_counter();count=processor_count[0]
                with torch.inference_mode():
                    answer=model.chat(image=None,msgs=[dict(role='user',content=[im,prompt])],
                        tokenizer=tok,processor=processor,sampling=False,stream=False,num_beams=1,max_new_tokens=128)
                torch.cuda.synchronize();assert processor_count[0]>count
                result[task]=dict(answer=answer,latency_s=time.perf_counter()-start,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
            stream.write(json.dumps(result,ensure_ascii=False)+'\n');results.append(result)
            print(f'{i}/{len(inputs)} {row["id"]}',flush=True)
    scored=[score(x,labels[x['id']]) for x in results]
    (a.output/'scored.json').write_text(json.dumps(scored,indent=2)+'\n')
    summary=summarize(scored,results);summary['peak_allocated_bytes']=torch.cuda.max_memory_allocated()
    summary['peak_reserved_bytes']=torch.cuda.max_memory_reserved();summary['processor_calls']=processor_count[0]
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
