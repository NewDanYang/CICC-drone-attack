"""Link actual model decisions, consumed pixels, servo logs and wire commands."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re

def stamp(row):return datetime.fromisoformat(row['wall_time']).timestamp()
def read(path):return [json.loads(s) for s in path.read_text().splitlines()]

parser=argparse.ArgumentParser()
parser.add_argument('session',type=Path)
parser.add_argument('--limit',type=int,default=8)
args=parser.parse_args()
sources={};decisions={}
for log in (args.session/'model').glob('*/audit.jsonl'):
    for row in read(log):
        if row['kind']=='model_source':
            sources[row['decision']]=dict(row,image=str((log.parent/row['image']).relative_to(args.session)))
        if row['kind']=='decision':decisions[row['decision']]=row
events=read(args.session/'audit/events.jsonl')
controls=[r for r in events if r['event']=='setpoint']
screens=[r for r in events if r['event']=='window_screenshot']
pixel=None;links=[];seen=set()
for row in events:
    message=row.get('message','')
    if row['event']=='rosout' and 'MULTIMODAL_PIXEL ' in message:pixel=row
    if (row['event']!='rosout' or not pixel or stamp(row)-stamp(pixel)>.35 or
            not re.search(r'\[VisualServo\]: (?:ALIGN -|APPROACH -|SPRINT_START)',message)):
        continue
    match=re.search(r'source=fm9g:[^ :]+:([^ ]+)',pixel['message'])
    if not match or match[1] not in sources or match[1] in seen:continue
    identifier=match[1];seen.add(identifier)
    following=next((r for r in controls if 0<=stamp(r)-stamp(row)<=.15),None)
    screenshot=min(screens,key=lambda r:abs(stamp(r)-stamp(row))) if screens else None
    if screenshot and abs(stamp(screenshot)-stamp(row))>1.5:screenshot=None
    links.append(dict(decision=identifier,model_source=sources[identifier],
        semantic_decision=decisions.get(identifier),consumption=pixel,servo=row,
        following_wire_command=following,nearby_actual_window=screenshot))
    if len(links)>=args.limit:break
print(json.dumps(links,ensure_ascii=False,indent=2))
