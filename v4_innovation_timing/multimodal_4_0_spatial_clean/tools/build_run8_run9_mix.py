#!/usr/bin/env python3
"""Build the second controlled candidate: clean train + run8 train, run9 val."""
import collections, hashlib, json
from pathlib import Path

BASE=Path('/root/gpufree-data/mm40_spatial_clean'); ROOT=Path('/root/gpufree-data/mm41_run8_mix')
COLORS={'red':'红色','purple':'紫色','blue':'蓝色'}
def prompt(c):
    return (f'请定位图片中实际可见的{COLORS[c]}气球球体，排除小车、绳子和墙面。'
            '只输出一个原生格式框：<box>x1 y1 x2 y2</box>。四个坐标按当前图片宽高归一化到0到1000，'
            'x向右增加、y向下增加；没有实际可见目标时输出<box>None</box>。不要解释，不要Markdown。')
def ans(r):
    if not r.get('present') or r.get('bbox') is None:return '<box>None</box>'
    b=r['bbox'];v=[round(b[i]*(1000/(640 if i%2==0 else 480))) for i in range(4)]
    return '<box>%d %d %d %d</box>'%tuple(v)
def ex(r):return {'id':r['id']+'_native','image':r['image_path'],'conversations':[{'role':'user','content':prompt(r['color'])},{'role':'assistant','content':ans(r)}]}
def main():
    old=json.loads((BASE/'data/cases.json').read_text()); train=[r for r in old if r['split']=='train']
    # Add all run8 rows only after the original visual-review labels have been
    # retained in the manifest. Test remains run10 and is never used here.
    train += [dict(r,split='train',source_run='run8') for r in old if r['split']=='validation']
    audit=json.loads((BASE/'run9_audit.json').read_text())
    val=[]
    for x in audit['items']:
        val.append({'id':f"run9_{x['frame']:05d}_{x['color']}",'run':'run9','image':x['image'],'frame':x['frame'],'color':x['color'],'bbox':x['bbox'],'present':True,'clipped':x['bbox'][0]==0 or x['bbox'][1]==0 or x['bbox'][2]>=640 or x['bbox'][3]>=480,'split':'validation','source_run':'run9','image_path':f"/root/gpufree-data/mm36_data/run9/{x['image']}",'label_source':'object proposal audited by HSV hue fraction >=0.25'})
    test=[r for r in old if r['split']=='test']
    ROOT.joinpath('data').mkdir(parents=True,exist_ok=True)
    for s,rs in [('train',train),('validation',val),('test',test)]:
        ROOT.joinpath('data',f'{s}.json').write_text(json.dumps([ex(r) for r in rs],ensure_ascii=False,indent=2)+'\n')
    allr=train+val+test; ROOT.joinpath('data','cases.json').write_text(json.dumps(allr,ensure_ascii=False,indent=2)+'\n')
    receipt={'task':'4.0 run8 mix','train_questions':len(train),'validation_questions':len(val),'test_questions':len(test),'positive_by_split':{s:dict(collections.Counter(r['color'] for r in rs if r.get('present'))) for s,rs in [('train',train),('validation',val),('test',test)]},'source_runs':{'train':['run3','run7','run8'],'validation':['run9'],'test':['run10']},'run9_hue_audit':str(BASE/'run9_audit.json'),'cases_sha256':hashlib.sha256(ROOT.joinpath('data','cases.json').read_bytes()).hexdigest()}
    ROOT.joinpath('data','receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
