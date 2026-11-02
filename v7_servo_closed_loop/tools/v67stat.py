import json,sys
p=sys.argv[1]
kinds={}; pubs=[]; ms=[]
for line in open(p,errors='replace'):
    try: e=json.loads(line)
    except: continue
    k=e.get('kind'); kinds[k]=kinds.get(k,0)+1
    if k=='publish': pubs.append(e)
    if k=='v6_measure': ms.append(e)
tot=len(pubs); box=[x for x in pubs if x.get('bbox')]
print('kinds',kinds)
print('publish total',tot,'with box',len(box),'%.0f%%'%(100.0*len(box)/max(tot,1)))
modes={}
for x in box: modes[x.get('guard_mode')]=modes.get(x.get('guard_mode'),0)+1
print('guard modes',modes)
areas=sorted(((x['bbox'][2]-x['bbox'][0])*(x['bbox'][3]-x['bbox'][1])/307200.0) for x in box)
print('area p50 %.4f p90 %.4f max %.4f'%(areas[len(areas)//2],areas[int(len(areas)*0.9)],areas[-1]))
print('--- publishes 05:45:23.5-05:45:27.5')
for x in pubs:
    t=x['wall_time'][11:23]
    if '05:45:23' <= t <= '05:45:27.9':
        b=x.get('bbox')
        print(t, x.get('guard_mode'), 'z=%s'%(None if x.get('odom_z') is None else round(x['odom_z'],2)), 'bbox=%s'%([round(v) for v in b] if b else None), 'age=%s'%(None if x.get('guard_age_s') is None else round(x['guard_age_s'],2)))
print('--- measures')
for m in ms: print(m['wall_time'][11:23], m['mode'], [round(v) for v in m['bbox']], 'age=%.2f'%m['age_s'])