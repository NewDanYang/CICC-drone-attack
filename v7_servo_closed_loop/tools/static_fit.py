import json,sys,math
trial=sys.argv[1]
times=[41.39,41.99,42.57,43.17,43.76,44.33,44.94,45.55,46.16,46.77]
hs=[51,44,37,33,35,40,45,59,85,159]
us=[261.5,242,339,362.5,348.5,342.5,320.5,310,283.5,216]
od=[]
for line in open(trial, errors='replace'):
    try: d=json.loads(line)
    except: continue
    if d.get('event')!='odom_sample': continue
    if 'rflysim' not in d['topic']: continue
    w=d.get('wall_time','')[11:23]
    if not ('04:09:35' <= w <= '04:09:50'): continue
    sec=int(w[6:8])+int(w[9:12])/1000.0
    p=d['position']
    od.append((sec,p['x'],p['y'],p['z']))
print('odom n',len(od))
def at(t):
    for i in range(len(od)-1):
        if od[i][0]<=t<=od[i+1][0]:
            a,b=od[i],od[i+1]; k=(t-a[0])/(b[0]-a[0]+1e-9)
            return (a[1]+k*(b[1]-a[1]), a[2]+k*(b[2]-a[2]), a[3]+k*(b[3]-a[3]))
    return None
pts=[at(t) for t in times]
for t,p in zip(times,pts): print('  %5.2f p=(%6.3f,%6.3f,%5.3f)' % (t,p[0],p[1],p[2]))
best=None
for i in range(1,600):
    Z0=0.3+i*0.005
    for j in range(1,400):
        K=j*2.0
        err=0.0
        for k,(p,h) in enumerate(zip(pts,hs)):
            D=math.dist((p[0],p[1]),(pts[0][0],pts[0][1]))
            Zh=Z0-D
            if Zh<0.05: err+=1e6; continue
            pred=K/Zh
            err+=(math.log(pred/h))**2
        if best is None or err<best[0]: best=(err,Z0,K)
err,Z0,K=best
print('best Z0=%.3f K=%.1f rms_log=%.4f' % (Z0,K,math.sqrt(err/len(hs))))
for k,(p,h) in enumerate(zip(pts,hs)):
    D=math.dist((p[0],p[1]),(pts[0][0],pts[0][1]))
    print('  %5.2f D=%.3f Z=%.3f h_pred=%6.1f h_obs=%d' % (times[k],D,Z0-D,K/max(Z0-D,0.05),h))
