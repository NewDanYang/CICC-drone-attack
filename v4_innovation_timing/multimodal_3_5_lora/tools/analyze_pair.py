"""Score frozen paired predictions, keeping run/color/size and label provenance visible."""
import argparse,csv,json
from collections import Counter
from pathlib import Path
from evaluate import score,summarize

p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--base',type=Path,required=True)
p.add_argument('--adapter',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
cases=json.loads((a.data/'cases.json').read_text());labels={r['id']:r for r in cases if r['split']=='test'}
pred={};scored={};summaries={}
for group,folder in [('base',a.base),('adapter',a.adapter)]:
    rows=[json.loads(line) for line in (folder/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    assert {r['id'] for r in rows}==set(labels)
    for r in rows:assert r['sha256']==labels[r['id']]['sha256']
    pred[group]=rows;scored[group]={r['id']:score(r,labels[r['id']]) for r in rows}
    summaries[group]=summarize(list(scored[group].values()),rows)

def frac(row,key):return row[key]/row['positive'] if row['positive'] else 0
b=summaries['base']['overall'];m=summaries['adapter']['overall']
region_gate=(frac(m,'region_hits')>=.85 and (frac(m,'region_hits')-frac(b,'region_hits')>=.10 or
    frac(b,'region_hits')>=.85 and frac(m,'region_hits')>=frac(b,'region_hits')) and
    all(frac(row,'region_hits')>=.75 for row in summaries['adapter']['colors'].values()) and m['region_negative_errors']<=1)
geometry_gate=(frac(m,'geometry_hits')>=.70 and all(frac(row,'geometry_hits')>=.60 for row in summaries['adapter']['colors'].values())
    and frac(summaries['adapter']['colors']['red'],'geometry_hits')>=.70 and m['bbox_negative_errors']<=1)
prior={c:Counter(r['region'] for r in cases if r['split']=='train' and r['present'] and r['color']==c).most_common(1)[0][0]
    for c in ['red','purple','blue']}
off_prior=[r['id'] for r in labels.values() if r['present'] and r['region']!=prior[r['color']]]
result=dict(summaries=summaries,gates=dict(region=region_gate,geometry=geometry_gate,flight_eligible=region_gate and geometry_gate),
    training_color_region_prior=prior,prior_positive_hits=sum(r['region']==prior[r['color']] for r in labels.values() if r['present']),
    off_prior=dict(n=len(off_prior),**{g:sum(scored[g][i]['region_correct'] for i in off_prior) for g in scored}),
    trials={},size_bins={},manual_bbox_subset={})
for trial in sorted({r['trial'] for r in labels.values()}):
    ids=[r['id'] for r in labels.values() if r['trial']==trial]
    result['trials'][trial]={g:dict(n=len(ids),positive=sum(labels[i]['present'] for i in ids),
        region_hits=sum(scored[g][i]['region_correct'] and labels[i]['present'] for i in ids),
        geometry_hits=sum(scored[g][i]['geometry_pass'] for i in ids)) for g in scored}
for name,lo,hi in [('small',0,40),('medium',40,80),('large',80,10000)]:
    ids=[r['id'] for r in labels.values() if r['present'] and lo<max(r['bbox'][2]-r['bbox'][0],r['bbox'][3]-r['bbox'][1])<=hi]
    result['size_bins'][name]=dict(n=len(ids),**{g:dict(region_hits=sum(scored[g][i]['region_correct'] for i in ids),
        geometry_hits=sum(scored[g][i]['geometry_pass'] for i in ids)) for g in scored})
ids=[r['id'] for r in labels.values() if r['present'] and 'manually traced' in r['label_source']]
result['manual_bbox_subset']=dict(n=len(ids),**{g:dict(region_hits=sum(scored[g][i]['region_correct'] for i in ids),
    geometry_hits=sum(scored[g][i]['geometry_pass'] for i in ids)) for g in scored})
a.output.mkdir(parents=True,exist_ok=True)
(a.output/'paired_summary.json').write_text(json.dumps(result,indent=2)+'\n')
with (a.output/'paired.csv').open('w',newline='',encoding='utf-8') as f:
    fields=['id','trial','color','present','clipped','label_source','truth_bbox','base_region_correct','adapter_region_correct',
        'base_iou','adapter_iou','base_center_error_px','adapter_center_error_px','base_geometry_pass','adapter_geometry_pass']
    out=csv.DictWriter(f,fieldnames=fields);out.writeheader()
    for i,r in labels.items():
        row={k:r[k] for k in ['id','trial','color','present','clipped','label_source']};row['truth_bbox']=json.dumps(r['bbox'])
        for g in scored:
            for key in ['region_correct','iou','center_error_px','geometry_pass']:row[g+'_'+key]=scored[g][i][key]
        out.writerow(row)
print(json.dumps(result['gates'],indent=2))
