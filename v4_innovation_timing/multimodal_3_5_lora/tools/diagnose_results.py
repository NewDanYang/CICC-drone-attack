"""Post-test error accounting; no inference, model selection or threshold changes."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True)
p.add_argument('--base',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
labels={r['id']:r for r in json.loads((a.data/'cases.json').read_text()) if r['split']=='test'}
all_rows={g:{r['id']:r for r in json.loads((folder/'scored.json').read_text())}
    for g,folder in [('base',a.base),('adapter',a.adapter)]}
report={}
for g,rows in all_rows.items():
    assert set(rows)==set(labels)
    pos=[r for r in rows.values() if r['present']]
    bins=dict(pass_both=0,iou_fail_only=0,center_fail_only=0,both_fail=0,missing_or_invalid_bbox=0)
    for r in pos:
        if r['center_error_px'] is None:bins['missing_or_invalid_bbox']+=1;continue
        i=r['iou']>=.5;c=r['center_error_px']<=r['center_error_threshold_px']
        bins['pass_both' if i and c else 'iou_fail_only' if c else 'center_fail_only' if i else 'both_fail']+=1
    raw=[json.loads(line) for line in ((a.base if g=='base' else a.adapter)/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    report[g]=dict(positive_failure_bins=bins,region_error_ids=[r['id'] for r in pos if not r['region_correct']],
        missing_bbox_ids=[r['id'] for r in pos if not r['bbox_nonempty']],
        parse_error_ids=[r['id'] for r in rows.values() if r.get('bbox_parse_error') or r.get('region_parse_error')],
        negative_error_rows=[r for r in rows.values() if not r['present'] and (not r['region_correct'] or r['bbox_nonempty'] or not r['bbox_valid'])],
        median_two_call_latency_s=statistics.median(r['region']['latency_s']+r['bbox']['latency_s'] for r in raw))
matched=[i for i,r in all_rows['base'].items() if r['present'] and r['center_error_px'] is not None and all_rows['adapter'][i]['center_error_px'] is not None]
report['matched_center_errors']=dict(n=len(matched),**{g:statistics.median(rows[i]['center_error_px'] for i in matched) for g,rows in all_rows.items()})
report['region_changes']=dict(improved=[i for i in labels if labels[i]['present'] and not all_rows['base'][i]['region_correct'] and all_rows['adapter'][i]['region_correct']],
    regressed=[i for i in labels if labels[i]['present'] and all_rows['base'][i]['region_correct'] and not all_rows['adapter'][i]['region_correct']])
report['manual_positive_rows']={i:dict(label=labels[i],base=all_rows['base'][i],adapter=all_rows['adapter'][i]) for i in labels if labels[i]['present'] and 'manually traced' in labels[i]['label_source']}
if a.output.exists():raise RuntimeError('Refuse overwrite')
a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({g:report[g]['positive_failure_bins'] for g in ['base','adapter']}))
