"""Conservative offline cloud/odometry validator; no ROS or flight APIs."""
from dataclasses import dataclass
import math

class Reject(ValueError): pass

def finite(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(float(x))
def vec(v,n):
    if not isinstance(v,(list,tuple)) or len(v)!=n or not all(finite(x) for x in v): raise Reject("invalid_vector")
    return tuple(float(x) for x in v)
def quat(q):
    q=vec(q,4); n=math.sqrt(sum(x*x for x in q))
    if n<1e-12: raise Reject("zero_quaternion")
    return tuple(x/n for x in q)
def mat(q):
    x,y,z,w=quat(q)
    return ((1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)),(2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)),(2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)))
def mm(a,b): return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
def mv(a,v): return tuple(sum(a[i][j]*v[j] for j in range(3)) for i in range(3))
def add(a,b): return tuple(x+y for x,y in zip(a,b))
@dataclass(frozen=True)
class Extrinsic:
    rotation: tuple
    translation: tuple
    source: str='sensor'
    def checked(self):
        r=self.rotation
        if not isinstance(r,(list,tuple)) or len(r)!=3 or any(len(row)!=3 for row in r): raise Reject("invalid_rotation")
        r=tuple(tuple(float(x) for x in row) for row in r)
        rt=tuple(zip(*r)); gram=mm(rt,r); det=r[0][0]*(r[1][1]*r[2][2]-r[1][2]*r[2][1])-r[0][1]*(r[1][0]*r[2][2]-r[1][2]*r[2][0])+r[0][2]*(r[1][0]*r[2][1]-r[1][1]*r[2][0])
        if any(not finite(x) for row in r for x in row) or max(abs(gram[i][j]-(i==j)) for i in range(3) for j in range(3))>1e-6 or abs(det-1)>1e-6: raise Reject("invalid_rotation")
        return Extrinsic(r,vec(self.translation,3),self.source)
@dataclass(frozen=True)
class Pair:
    odom: dict
    skew: float
    age: float

def pair(cloud,history,now,max_age=.25,max_skew=.05):
    if not isinstance(cloud,dict) or not finite(cloud.get('stamp')) or cloud['stamp']<=0: raise Reject('invalid_cloud_stamp')
    t=float(cloud['stamp']); age=float(now)-t
    if age<0: raise Reject('future_cloud')
    if age>max_age: raise Reject('stale_cloud')
    rows=[]; seen=set()
    for o in history:
        if not isinstance(o,dict) or not finite(o.get('stamp')): continue
        s=float(o['stamp'])
        if s in seen: raise Reject('duplicate_odom_stamp')
        seen.add(s); rows.append((s,o))
    rows.sort()
    before=[x for x in rows if x[0]<=t]; after=[x for x in rows if x[0]>=t]
    if not before or not after: raise Reject('no_interpolation_bracket')
    a,oa=before[-1]; b,ob=after[0]
    if max(abs(t-a),abs(b-t))>max_skew: raise Reject('timestamp_skew')
    if any(float(now)-s>max_age or s>float(now) for s in (a,b)): raise Reject('stale_odom')
    if oa.get('parent_frame')!='world' or oa.get('child_frame')!='body' or ob.get('parent_frame')!='world' or ob.get('child_frame')!='body': raise Reject('odom_frame')
    if a==b: chosen=oa
    else:
        u=(t-a)/(b-a); pa=vec(oa['position'],3); pb=vec(ob['position'],3); qa=quat(oa['quaternion']); qb=quat(ob['quaternion'])
        if sum(x*y for x,y in zip(qa,qb))<0: qb=tuple(-x for x in qb)
        chosen={'stamp':t,'position':[(1-u)*pa[i]+u*pb[i] for i in range(3)],'quaternion':quat([(1-u)*qa[i]+u*qb[i] for i in range(4)]),'parent_frame':'world','child_frame':'body'}
    return Pair(chosen,0.0,age)
def transform(points,pair_info,ex,cloud_kind='sensor'):
    if cloud_kind not in ('sensor','body'): raise Reject('cloud_frame')
    ex=ex.checked(); ro=mat(pair_info.odom['quaternion']); to=vec(pair_info.odom['position'],3)
    r=mm(ro,ex.rotation) if cloud_kind=='sensor' else ro; t=add(mv(ro,ex.translation),to) if cloud_kind=='sensor' else to
    return [add(mv(r,vec(p,3)),t) for p in points]
