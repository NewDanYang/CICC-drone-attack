from pathlib import Path
from collections import Counter
import sys, rosbag

run = Path(sys.argv[1]); bag = run / 'evidence.bag'
events, objects = [], []
with rosbag.Bag(str(bag)) as b:
    for topic, msg, stamp in b.read_messages(topics=['/rosout','/objects']):
        t = stamp.to_sec()
        if topic == '/rosout':
            if any(k in msg.msg for k in ('Visual Servo Started','Target lost','Area ', 'SPRINT', 'Sprint completed', 'Mission Completed')):
                events.append((t, msg.msg))
        else:
            rows=[]
            for o in msg.objects:
                w=o.right_bottom_x-o.left_top_x; h=o.right_bottom_y-o.left_top_y
                rows.append((o.class_name,o.center_x,o.center_y,w,h,o.score))
            objects.append((t,rows))

sprint=next((t for t,s in events if 'SPRINT!' in s),None)
if sprint is None: raise SystemExit('No SPRINT event found')
done=next((t for t,s in events if 'Sprint completed' in s),sprint+0.4)
red=[]; classes=Counter()
for t,rows in objects:
    for r in rows:
        classes[r[0]]+=1
        if r[0]=='red_balloon': red.append((t,)+r[1:])
def window(lo,hi): return [r for r in red if lo<=r[0]<=hi]
before=window(sprint-5,sprint); during=window(sprint,done); after=window(done,done+8)
lines=['Trial: '+str(run),'User observation: red balloon not popped.',
       'Sprint interval %.3f..%.3f'%(sprint,done),'Classes: '+str(dict(classes)),
       'Red before/during/after: %d/%d/%d'%(len(before),len(during),len(after))]
if before:
    r=min(before,key=lambda x:abs(x[0]-sprint))
    lines.append('Nearest pre-sprint cx=%d cy=%d size=%dx%d score=%.3f'%(r[1],r[2],r[3],r[4],r[5]))
    lines.append('Pixel offset dx=%+.1f dy=%+.1f'%(r[1]-320,r[2]-240))
lines.append('Red detections continued after sprint; no pop evidence.' if after else 'No post-sprint red detection; target loss is not collision proof.')
text='\n'.join(lines)+'\n'; print(text); (run/'hit_analysis.txt').write_text(text,encoding='utf-8')

