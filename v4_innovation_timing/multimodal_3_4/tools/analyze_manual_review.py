"""Join frozen visual notes to raw decisions; quantify tile containment, not CV labels."""
import argparse
from collections import Counter,defaultdict
import json,math
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('diagnosis',type=Path);args=p.parse_args()
records={r['decision']:r for r in json.loads((args.diagnosis/'decision_index.json').read_text(encoding='utf-8'))}
annotations=json.loads((args.diagnosis/'manual_annotations.json').read_text(encoding='utf-8'))
joined=[]
for note in annotations['rows']:
    row=records[note['decision']];assert row['source_sha256']==note['source_sha256']
    result=dict(note,reason=row['reason'],model_roi_nonempty=row['model_box'] is not None,final_bbox=row['bbox'],
        positive_tile_indices=row['positive_indices'])
    if note['visible_bbox']:
        x1,y1,x2,y2=note['visible_bbox'];area=(x2-x1)*(y2-y1)
        contains=[];cover=[];margins=[]
        for i,(a,b,c,d) in enumerate(row['boxes']):
            overlap=max(0,min(c,x2)-max(a,x1))*max(0,min(d,y2)-max(b,y1))
            cover.append(overlap/area)
            if a<=x1<x2<=c and b<=y1<y2<=d:
                contains.append(i);margins.append(min(x1-a,y1-b,c-x2,d-y2))
        result.update(visible_width=x2-x1,visible_height=y2-y1,
            width_to_tile_ratio=(x2-x1)/256,height_to_tile_ratio=(y2-y1)/192,
            fully_containing_tile_indices=contains,maximum_visible_area_coverage=max(cover),
            max_margin_in_containing_tile=max(margins) if margins else None,
            positive_complete_tiles=sorted(set(contains)&set(row['positive_indices'])))
    joined.append(result)
summary={}
for color in ('red','purple','blue'):
    part=[r for r in joined if r['color']==color]
    summary[color]=dict(reviewed=len(part),visibility=dict(Counter(r['visibility'] for r in part)),
        visible_outcomes=dict(Counter(r['reason'] for r in part if r['visibility']=='visible')),
        missing_roi_visibility=dict(Counter(r['visibility'] for r in part if not r['model_roi_nonempty'])),
        full_balloons_with_bbox_notes=sum(r['visible_bbox'] is not None and not r['original_frame_clipped'] for r in part))
out=dict(summary=summary,rows=joined,
    scope='red all source frames; purple/blue are diagnostic samples selected by output category, not estimates of overall rates',
    bbox_uncertainty_px=4)
(args.diagnosis/'manual_analysis.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2))
for r in joined:
    if r.get('visible_bbox'):print(r['review_number'],r['decision'],r['visible_bbox'],r['fully_containing_tile_indices'],r['positive_complete_tiles'])
