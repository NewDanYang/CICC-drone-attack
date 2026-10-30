#!/usr/bin/env python3
import json, math
import numpy as np
root='/root/gpufree-data/mm41_run8_mix'
cases={r['id']:r for r in json.load(open(root+'/data/cases.json'))}
def get_stats():
    vals={}
    for x in json.load(open(root+'/eval_validation/scored.json')):
        r=cases.get(x['id']); p=x.get('predicted_bbox_px'); b=r and r.get('bbox')
        if not (x.get('present') and p and b): continue
        c=r['color']; vals.setdefault(c,[]).append(((p[0]+p[2])/2-(b[0]+b[2])/2,(p[1]+p[3])/2-(b[1]+b[3])/2,(p[2]-p[0])/(b[2]-b[0]),(p[3]-p[1])/(b[3]-b[1])))
    return {c:np.mean(v,0) for c,v in vals.items()}
def score(z,b):
    x,y,z2,w=b; inter=max(0,min(z[2],z2)-max(z[0],x))*max(0,min(z[3],w)-max(z[1],y)); u=(z[2]-z[0])*(z[3]-z[1])+(z2-x)*(w-y)-inter; i=inter/u if u else 0; e=math.hypot((z[0]+z[2]-x-z2)/2,(z[1]+z[3]-y-w)/2); t=max(8,.2*math.hypot(z2-x,w-y)); return i,e,i>=.5 and e<=t
def main():
    s=get_stats(); out=[]; before=[]; after=[]
    for x in json.load(open(root+'/eval_test/scored.json')):
        r=cases.get(x['id']); p=x.get('predicted_bbox_px'); b=r and r.get('bbox')
        if not (x.get('present') and p and b): continue
        bias=s[r['color']]; cx=(p[0]+p[2])/2-bias[0]; cy=(p[1]+p[3])/2-bias[1]; ww=(p[2]-p[0])/bias[2]; hh=(p[3]-p[1])/bias[3]; q=[max(0,cx-ww/2),max(0,cy-hh/2),min(640,cx+ww/2),min(480,cy+hh/2)]
        before.append(x['geometry_pass']); after.append(score(q,b)[2]); out.append({'id':x['id'],'color':r['color'],'bbox':b,'pred':p,'calibrated':q,'before':x['geometry_pass'],'after':score(q,b)})
    result={'calibration':{c:v.tolist() for c,v in s.items()},'before_hits':sum(before),'after_hits':sum(after),'n':len(after),'by_color':{c:{'before':sum(z['before'] for z in out if z['color']==c),'after':sum(z['after'][2] for z in out if z['color']==c),'n':sum(z['color']==c for z in out)} for c in s},'items':out}
    json.dump(result,open(root+'/eval_test/calibrated.json','w'),indent=2,default=int); print(json.dumps({k:v for k,v in result.items() if k!='items'},ensure_ascii=False,indent=2,default=int))
if __name__=='__main__':main()
