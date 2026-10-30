#!/usr/bin/env python3
"""Build a color-audited native-<box> dataset from real simulator captures.

The train split is rebuilt from the real run3/run7 rows, removing hue-mismatched
labels and overlapping cross-color boxes. Validation and test remain the
independent run8/run10 splits from the 3.7 receipt.
"""
from __future__ import annotations
import collections, hashlib, json, math
from pathlib import Path
import cv2
import numpy as np

ROOT = Path('/root/gpufree-data/mm40_spatial_clean')
SRC = Path('/root/gpufree-data/mm36_lora_v2/data/cases.json')
OLD = Path('/root/gpufree-data/mm37_coord_only/data/cases.json')
IMG = Path('/root/gpufree-data/mm36_lora_v2/data/images')
COLORS = {'red': '红色', 'purple': '紫色', 'blue': '蓝色'}

def iou(a, b):
    x = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = x*y
    ua = (a[2]-a[0])*(a[3]-a[1]); ub = (b[2]-b[0])*(b[3]-b[1])
    return inter/(ua+ub-inter) if ua+ub-inter else 0.0

def hue_fraction(row):
    if not row.get('bbox') or not row.get('present'):
        return 1.0
    path = IMG / row['image']
    im = cv2.imread(str(path))
    if im is None: return 0.0
    x1,y1,x2,y2 = map(int,row['bbox'])
    crop = im[max(0,y1):min(im.shape[0],y2), max(0,x1):min(im.shape[1],x2)]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h = hsv[:,:,0].astype(float)*2; s=hsv[:,:,1]; v=hsv[:,:,2]
    m=(s>80)&(v>40)
    if not m.any(): return 0.0
    if row['color']=='red': target=((h<25)|(h>330))&m
    elif row['color']=='purple': target=(h>=260)&(h<=330)&m
    else: target=(h>=190)&(h<=260)&m
    return float(target.sum()/m.sum())

def prompt(color):
    cn=COLORS[color]
    return (f'请定位图片中实际可见的{cn}气球球体，排除小车、绳子和墙面。'
            '只输出一个原生格式框：<box>x1 y1 x2 y2</box>。四个坐标按当前图片宽高归一化到0到1000，'
            'x向右增加、y向下增加；没有实际可见目标时输出<box>None</box>。不要解释，不要Markdown。')

def answer(row):
    if not row.get('present') or row.get('bbox') is None:
        return '<box>None</box>'
    b=row['bbox']; vals=[round(b[i]*(1000/(640 if i%2==0 else 480))) for i in range(4)]
    return '<box>%d %d %d %d</box>' % tuple(vals)

def example(row):
    return {'id': row['id']+'_native', 'image': row['image_path'],
            'conversations':[{'role':'user','content':prompt(row['color'])},
                             {'role':'assistant','content':answer(row)}]}

def main():
    old=json.loads(SRC.read_text()); hold=json.loads(OLD.read_text())
    train=[r for r in old if r.get('split')=='train']
    # Hue check is a deterministic audit aid; all retained rows remain backed
    # by the original human-reviewed real-frame annotations.
    retained=[]; rejected=[]
    for r in train:
        if r.get('present') and (max(r['bbox'][2]-r['bbox'][0], r['bbox'][3]-r['bbox'][1]) < 12 or hue_fraction(r)<0.20):
            rejected.append({'id':r['id'],'reason':'hue_or_tiny','hue_fraction':hue_fraction(r)})
        else: retained.append(dict(r))
    by_img=collections.defaultdict(list)
    for r in retained:
        if r.get('present') and r.get('bbox'): by_img[r['image']].append(r)
    bad_ids=set()
    for rs in by_img.values():
        for i,a in enumerate(rs):
            for b in rs[i+1:]:
                if a['color']!=b['color'] and iou(a['bbox'],b['bbox'])>=0.50:
                    bad_ids.update((a['id'],b['id']))
    for r in retained:
        if r['id'] in bad_ids: rejected.append({'id':r['id'],'reason':'cross_color_overlap'}); continue
        r['split']='train'; r['source_run']=r.get('run'); r['image_path']=str(IMG/r['image']);
    train=[r for r in retained if r['id'] not in bad_ids]
    val=[dict(r) for r in hold if r.get('split')=='validation']
    test=[dict(r) for r in hold if r.get('split')=='test']
    for r in val+test:
        r['image_path']=r.get('image_path') or r['image']
    ROOT.joinpath('data').mkdir(parents=True,exist_ok=True)
    sets={'train':train,'validation':val,'test':test}
    for split,rows in sets.items():
        ROOT.joinpath('data',f'{split}.json').write_text(json.dumps([example(r) for r in rows],ensure_ascii=False,indent=2)+'\n')
    allrows=train+val+test
    ROOT.joinpath('data','cases.json').write_text(json.dumps(allrows,ensure_ascii=False,indent=2)+'\n')
    receipt={'task':'4.0 clean native box','train_questions':len(train),'validation_questions':len(val),'test_questions':len(test),
             'positive_by_split':{s:dict(collections.Counter(r['color'] for r in rs if r.get('present'))) for s,rs in sets.items()},
             'negative_by_split':{s:sum(not r.get('present') for r in rs) for s,rs in sets.items()},
             'source_runs':{s:sorted(set(r.get('source_run') or r.get('run') for r in rs)) for s,rs in sets.items()},
             'rejected_train':rejected,'hue_threshold':0.20,'cross_split_grouping':'train run3/run7; validation run8; test run10'}
    receipt['cases_sha256']=hashlib.sha256(ROOT.joinpath('data','cases.json').read_bytes()).hexdigest()
    ROOT.joinpath('data','receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
