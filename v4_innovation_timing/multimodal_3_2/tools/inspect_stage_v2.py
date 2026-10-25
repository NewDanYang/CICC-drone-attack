"""Read-only diagnosis of pose, command and safety ordering."""
import argparse
import json
import math
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('session',type=Path)
args=parser.parse_args()
last_odom=None
last_control=None
selected=[]
for line in (args.session/'audit/events.jsonl').read_text(encoding='utf-8').splitlines():
    row=json.loads(line)
    if row['event']=='odom': last_odom=row
    if row['event']=='setpoint': last_control=row
    message=row.get('message','')
    if row['event']=='rosout' and any(key in message for key in
        ('MULTIMODAL_STAGE_START','SEARCH_ANCHOR','Safety','SAFETY','boundary','Target lost.', 'checkArrival')):
        if 'Target lost.' in message and sum('Target lost.' in r.get('message','') for r in selected)>=5: continue
        item={'time':row['wall_time'],'message':message,'odom':last_odom,'control':last_control}
        selected.append(item)
print(json.dumps(selected,ensure_ascii=False,indent=2))
