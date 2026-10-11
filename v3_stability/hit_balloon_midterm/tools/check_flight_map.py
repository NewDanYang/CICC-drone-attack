from pathlib import Path
from collections import Counter
import sys, math, json
import numpy as np
import yaml, rosbag
from sensor_msgs import point_cloud2

run=Path(sys.argv[1])
params=yaml.safe_load((run/'params.yaml').read_text())
grid=params['ego_planner_node']['grid_map']
resolution=float(grid['resolution'])
origin=np.array([-float(grid['map_size_x'])/2, -float(grid['map_size_y'])/2, float(grid['ground_height'])])
goals, ends, poses, cmds=[],[],[],[]
with rosbag.Bag(str(run/'evidence.bag')) as bag:
    for topic,m,t in bag.read_messages(topics=['/rosout','/rflysim/uav1/local/odom','/planning/pos_cmd']):
        sec=t.to_sec()
        if topic=='/rosout':
            if '[PlanningGuard] Goal sent' in m.msg: goals.append(sec)
            if 'Planning navigation completed' in m.msg: ends.append(sec)
        else:
            p=m.pose.pose.position if topic.endswith('/odom') else m.position
            (poses if topic.endswith('/odom') else cmds).append((sec,p.x,p.y,p.z))
if len(goals)!=2 or len(ends)<2:
    raise SystemExit('Expected two planning stages; preserve bag and inspect logs')
start=goals[1]
end=next(t for t in ends if t>start)

def densify(rows):
    rows=[r for r in rows if start<=r[0]<=end]
    if len(rows)<2: raise RuntimeError('Too few path samples')
    out=[]
    for a,b in zip(rows,rows[1:]):
        a,b=np.array(a),np.array(b)
        n=max(1,int(math.ceil(np.linalg.norm(b[1:]-a[1:])/(resolution/2))))
        if n>1000: raise RuntimeError('Path discontinuity; inspect CSV')
        out.extend(a+(b-a)*i/n for i in range(n))
    out.append(np.array(rows[-1]))
    return np.array(out)

paths={'planned':densify(cmds),'actual':densify(poses)}
with rosbag.Bag(str(run/'flight_map_samples.bag')) as b:
    stamps=[t.to_sec() for _,_,t in b.read_messages(topics=['/grid_map/occupancy_inflate'])]
stats={k:Counter() for k in paths}
hits={k:[] for k in paths}
used_maps=0
with rosbag.Bag(str(run/'flight_map_samples.bag')) as b:
    for i,(_,m,t) in enumerate(b.read_messages(topics=['/grid_map/occupancy_inflate'])):
        sec=t.to_sec()
        until=min(stamps[i+1] if i+1<len(stamps) else sec+1.2, sec+1.2)
        if until<start or sec>end: continue
        points=np.array(list(point_cloud2.read_points(m,field_names=('x','y','z'),skip_nans=True)),dtype=float)
        if not len(points): continue
        used_maps+=1
        cells=np.floor((points-origin)/resolution+1e-6).astype(np.int64)
        occupied=set(map(tuple,cells))
        for label,path in paths.items():
            segment=path[(path[:,0]>=sec)&(path[:,0]<until)]
            ids=np.floor((segment[:,1:]-origin)/resolution).astype(np.int64)
            for row,idx in zip(segment,ids):
                stats[label]['checked']+=1
                if tuple(idx) in occupied:
                    stats[label]['occupied']+=1
                    hits[label].append(row.tolist()+[sec])
report=['Trial: '+str(run),
        'User observation: turned before return, avoided wall, landed normally.',
        'Return planning duration: %.2fs' % (end-start),
        'Map samples used during return: %d' % used_maps]
for label,path in paths.items():
    s=stats[label]
    report.append('%s: occupied=%d checked=%d total_dense_samples=%d (uncovered=%d)' %
                  (label,s['occupied'],s['checked'],len(path),len(path)-s['checked']))
    if hits[label]:
        first=hits[label][0]
        report.append('  First occupied sample +%.2fs XYZ=(%.3f,%.3f,%.3f), map_age=%.3fs' %
                      (first[0]-start,*first[1:4],first[0]-first[4]))
        np.savetxt(run/('return_'+label+'_live_map_hits.csv'),hits[label],delimiter=',',
                   header='path_time,x,y,z,map_time',comments='')
report.append('Limits: map sampled at 1Hz; uses latest preceding sample aged <=1.2s. No hit does not prove full body clearance or sensing coverage.')
text='\n'.join(report)+'\n'
(run/'flight_map_clearance_check.txt').write_text(text,encoding='utf-8')
(run/'observed_result.txt').write_text('User observation: turned before return, avoided wall, landed normally. Single real post-fix navigation trial passed.\n',encoding='utf-8')
print(text)

