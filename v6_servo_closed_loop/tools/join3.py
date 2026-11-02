import json
gt={}
for l in open('hsv_gt.jsonl'):
    o=json.loads(l); gt[o['image']]=o.get('gt')
rows=[]
for line in open('audit.jsonl'):
    o=json.loads(line)
    if o.get('kind')!='decision': continue
    d=o.get('decision');
    rows.append((o.get('wall_time','')[11:22], o.get('mode'), d, o.get('source_frame'), o.get('source_age_s'), o.get('model_track_age_s'), gt.get(d+'.png'), [round(v,1) for v in (o.get('bbox') or [])]))
print('total decisions', len(rows), 'with gt', sum(1 for r in rows if r[6]))
for r in rows:
    if '04:09:4' <= r[0] <= '04:10:05' or (r[6] and r[0] >= '04:09:40'):
        print(r[0], r[1], 'f%s' % r[3], 'age', round(r[4] or 0,2), 'm', round(r[5] or 0,2), 'gt', r[6], 'box', r[7])
