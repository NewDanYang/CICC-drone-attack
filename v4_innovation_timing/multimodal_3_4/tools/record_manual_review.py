"""Serialize the single-reviewer visual notes; no model answers read here."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('diagnosis',type=Path);args=p.parse_args()
selection=json.loads((args.diagnosis/'review_selection.json').read_text(encoding='utf-8'))
red=json.loads((args.diagnosis/'red_all/index.json').read_text(encoding='utf-8'))
# All 102 red initialization source PNGs were reviewed through numbered sheets;
# ambiguous/edge cases and all five complete red balloons also viewed at 640x480.
red_visible={7,8,9,22,23,80,81,82};red_uncertain={21}
red_boxes={7:[0,306,19,357],8:[270,283,299,324],9:[481,286,514,328],
    22:[159,287,194,331],23:[368,286,398,324],80:[332,402,443,480],
    81:[605,344,640,431],82:[503,254,545,302]}
blue_visible={1,4,5,6,11,12,16,18,19,22,23};blue_uncertain={21}
purple_visible={32,33,34,37,39,41,44,45,46,48,50};purple_uncertain={35}
notes=[]
for item in red:
    number=item['number'];visible=number in red_visible
    notes.append(dict(decision=item['decision'],trial=item['trial'],color='red',review_number='R'+str(number).zfill(3),
        source_sha256=item['source_sha256'],visibility='visible' if visible else 'uncertain' if number in red_uncertain else 'not_visible',
        visible_bbox=red_boxes.get(number),original_frame_clipped=number in {7,80,81} if visible else None))
for number,item in enumerate(selection,1):
    if item['color']=='red':continue
    visible=number in (blue_visible if item['color']=='blue' else purple_visible)
    uncertain=number in (blue_uncertain if item['color']=='blue' else purple_uncertain)
    notes.append(dict(decision=item['decision'],trial=item['trial'],color=item['color'],review_number=str(number).zfill(2),
        source_sha256=item['source_sha256'],visibility='visible' if visible else 'uncertain' if uncertain else 'not_visible',
        visible_bbox=None,original_frame_clipped=None))
report=dict(reviewed_at=datetime.now(timezone.utc).isoformat(),reviewer='single AI visual reviewer; no independent second annotation',
    scope='all 102 red initialization frames plus preselected blue/purple frames; correlated frames, diagnostic only',
    blindness='Contact sheets hide model answers/outcomes; prior project results and selection policy known; not an independent blind acceptance set',
    bbox_note='Visible balloon body only, excluding car/string; manually read from source PNG, approximately +/-4 px; clipped source is distinguished from tile clipping',
    rows=notes)
path=args.diagnosis/'manual_annotations.json';path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print('reviewed',len(notes),'sha256',hashlib.sha256(path.read_bytes()).hexdigest())
