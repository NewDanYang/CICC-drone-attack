"""Freeze by-run splits; offline proposals were visually reviewed, never runtime inputs."""
from collections import Counter
from datetime import datetime, timezone
import hashlib, json, re, tarfile
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
DATA=BASE/'evidence/data'
REMOTE='/root/gpufree-data/tcei_lora35/data'
COLORS={'red':'红色','purple':'紫色','blue':'蓝色'}

def prompts(color):
    cn=COLORS[color]
    coarse=(f'请只识别图片中实际可见的{cn}气球球体，排除小车、绳子和墙面。'
        '只输出JSON对象，格式为{"color":"'+color+'","region":"left|center|right"}。'
        'region按气球可见部分中心在整张图像横向的三等分区域填写。'
        '没有该颜色气球时输出{"color":"none","region":"none"}。不要解释，不要Markdown。')
    bbox=(f'请定位这张图片中实际可见的{cn}气球球体，排除小车、绳子、墙面。'
        '只输出一个JSON对象，只有bbox字段。bbox是气球可见部分的紧致矩形，'
        '格式为[x_min,y_min,x_max,y_max]，以当前这张图片的左上角为(0,0)、右下角为(1000,1000)，'
        '四个坐标均为0到1000之间的整数，x向右增加，y向下增加。'
        '没有实际可见'+cn+'气球时输出{"bbox":null}。不要解释，不要Markdown。')
    return {'region':coarse,'bbox':bbox}

def split(trial):
    m=re.search(r'_r([123])_',trial)
    if not m: raise ValueError(trial)
    return {'1':'train','2':'validation','3':'test'}[m[1]]

def main():
    pool=json.loads((DATA/'pool.json').read_text())
    cases=[]
    # All 19 sheets reviewed at full resolution by one AI visual reviewer.
    # Proposal 026 is a RED edge fragment incorrectly classified as blue. Reject it.
    for idx,row in enumerate(pool):
        if idx==26:continue
        for obj in row['proposals']:
            color=obj['name'].removesuffix('_balloon');b=obj['bbox']
            cx=(b[0]+b[2])/2
            cases.append(dict(id=row['id']+'_'+color,trial=row['trial'],split=split(row['trial']),
                image=row['file'],sha256=row['sha256'],color=color,present=True,bbox=b,
                region='left' if cx<640/3 else 'center' if cx<1280/3 else 'right',
                clipped=b[0]==0 or b[1]==0 or b[2]==640 or b[3]==480,
                label_source='timestamp-exact archived YOLO proposal + single AI visual confirmation',pool_index=idx))
    # Negatives are source PNGs previously reviewed as not visible, not YOLO missing detections.
    old=BASE.parent/'multimodal_3_4/evidence/diagnosis/manual_annotations.json'
    manual=json.loads(old.read_text())['rows']
    packed=BASE.parent/'multimodal_3_4/evidence/diagnostic_source_frames.tar.gz'
    counts=Counter()
    with tarfile.open(packed) as tar:
        for row in manual:
            gold=row.get('visible_bbox') is not None and row['visibility']=='visible'
            if row['visibility']!='not_visible' and not gold:continue
            sp=split(row['trial']);key=(sp,row['color'])
            if not gold and counts[key]>=4:continue
            if not gold:counts[key]+=1
            raw=tar.extractfile('sources/'+row['decision']+'.png').read()
            assert hashlib.sha256(raw).hexdigest()==row['source_sha256']
            name=('manual_' if gold else 'negative_')+row['decision']+'.png';(DATA/name).write_bytes(raw)
            b=row.get('visible_bbox');cx=(b[0]+b[2])/2 if b else None
            cases.append(dict(id=name[:-4],trial=row['trial'],split=sp,image=name,
                sha256=row['source_sha256'],color=row['color'],present=gold,bbox=b,
                region=('left' if cx<640/3 else 'center' if cx<1280/3 else 'right') if gold else 'none',
                clipped=bool(row['original_frame_clipped']) if gold else False,
                label_source='3.4 single AI manually traced bbox +/-4px' if gold else '3.4 single AI manual not_visible review'))
    by_hash={}
    for c in cases:
        if c['sha256'] in by_hash: assert by_hash[c['sha256']]==c['split'],'cross split hash leak'
        by_hash[c['sha256']]=c['split']
    for sp in ['train','validation','test']:
        examples=[]
        for c in cases:
            if c['split']!=sp:continue
            answers={'region':dict(color=c['color'] if c['present'] else 'none',region=c['region']),
                'bbox':dict(bbox=[round(v*(1000/640 if i%2==0 else 1000/480)) for i,v in enumerate(c['bbox'])] if c['bbox'] else None)}
            for task,prompt in prompts(c['color']).items():
                examples.append(dict(id=c['id']+'_'+task,image=REMOTE+'/'+c['image'],conversations=[
                    dict(role='user',content=prompt),dict(role='assistant',content=json.dumps(answers[task],ensure_ascii=False,separators=(',',':')))]))
        (DATA/(sp+'.json')).write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (DATA/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    receipt=dict(frozen_at=datetime.now(timezone.utc).isoformat(),reviewer='single AI visual reviewer; not independent blind human annotation',
        excluded_proposals=[dict(pool_index=26,reason='red fragment mislabeled blue')],
        bbox_quality='offline detector proposals visually checked for balloon body, not independently traced pixel gold',
        split_rule='entire round-1 trials train; round-2 validation; round-3 held-out test; no exact image hash shared',
        summary={sp:dict(images=len({c['sha256'] for c in cases if c['split']==sp}),
            positive=dict(Counter(c['color'] for c in cases if c['split']==sp and c['present'])),
            negative=dict(Counter(c['color'] for c in cases if c['split']==sp and not c['present']))) for sp in ['train','validation','test']},
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob('*.json') if p.name!='dataset_receipt.json'})
    (DATA/'dataset_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt['summary'],indent=2))

if __name__=='__main__':main()
