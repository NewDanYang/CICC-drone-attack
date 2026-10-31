#!/usr/bin/env python3
import collections, json, cv2
from pathlib import Path

ROOT=Path('/root/gpufree-data/mm36_data/run9')
rows=[json.loads(x) for x in (ROOT/'events.jsonl').read_text().splitlines() if json.loads(x).get('event')=='frame']
last=collections.defaultdict(lambda:-1000); out=[]
for r in rows:
    for p in r.get('proposals',[]):
        c=p.get('class_name','').replace('_balloon','')
        if c not in ('red','purple','blue') or p.get('score',0)<.5 or not r.get('odom') or r['odom'].get('speed',9)>.35: continue
        idx=int(r['image'].split('_')[1].split('.')[0])
        if idx-last[c]<3: continue
        im=cv2.imread(str(ROOT/r['image'])); x1,y1,x2,y2=map(int,(p['left'],p['top'],p['right'],p['bottom']))
        crop=im[max(0,y1):min(im.shape[0],y2),max(0,x1):min(im.shape[1],x2)]
        h=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV); H=h[:,:,0].astype(float)*2; S=h[:,:,1]; V=h[:,:,2]; m=(S>80)&(V>40); n=max(1,int(m.sum()))
        target=(((H<25)|(H>330)) if c=='red' else ((H>=260)&(H<=330)) if c=='purple' else ((H>=190)&(H<=260)))&m
        frac=float(target.sum()/n)
        if frac>=.25:
            last[c]=idx; out.append(dict(color=c,image=r['image'],bbox=[x1,y1,x2,y2],hue_fraction=round(frac,3),score=p.get('score'),speed=r['odom'].get('speed'),frame=idx))
print(json.dumps({'n':len(out),'by_color':dict(collections.Counter(x['color'] for x in out)),'items':out},ensure_ascii=False,indent=2))
