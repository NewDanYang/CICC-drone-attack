import json, sys
p=sys.argv[1]; lo=sys.argv[2]; hi=sys.argv[3]
for ln in open(p):
    d=json.loads(ln)
    if d.get('kind')!='publish': continue
    t=d.get('wall_time','')[11:22]
    if lo <= t <= hi:
        b=d.get('bbox')
        c=(round((b[0]+b[2])/2),round((b[1]+b[3])/2),round(b[2]-b[0]),round(b[3]-b[1])) if b else None
        print(t, c, d.get('guard_mode'), d.get('score'), d.get('reason') or d.get('source'))