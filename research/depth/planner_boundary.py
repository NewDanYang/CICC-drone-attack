"""Fail-closed research planner admission; no ROS or publication."""
import math
class BoundaryReject(ValueError): pass
def finite(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(float(x))
class PlannerBoundary:
    def __init__(self,required_frame,namespace='/research/planner',max_age=.25):
        if not isinstance(required_frame,str) or not required_frame: raise BoundaryReject('frame_required')
        if not isinstance(namespace,str) or not namespace.startswith('/research/') or '//' in namespace or '..' in namespace or namespace.endswith('/'): raise BoundaryReject('research_namespace_required')
        if not finite(max_age) or max_age<0: raise BoundaryReject('invalid_max_age')
        self.frame=required_frame; self.namespace=namespace; self.max_age=float(max_age); self.epoch=0; self.last_now=None; self.last_stamp=None; self.counters={}
    def reject(self,reason): self.counters['rejected_'+reason]=self.counters.get('rejected_'+reason,0)+1; return None
    def accept(self,record,now):
        if not finite(now) or now<0:return self.reject('invalid_clock')
        if self.last_now is not None and now<self.last_now:
            self.epoch+=1; self.last_stamp=None; self.last_now=now; self.counters['epoch_reset']=self.counters.get('epoch_reset',0)+1; return self.reject('clock_reset')
        self.last_now=float(now)
        if not isinstance(record,dict) or record.get('frame_id',record.get('frame'))!=self.frame:return self.reject('wrong_frame')
        stamp=record.get('acquisition_stamp',record.get('stamp'))
        if not finite(stamp) or stamp<=0:return self.reject('invalid_stamp')
        age=now-float(stamp)
        if age<0:return self.reject('future_cloud')
        if age>self.max_age:return self.reject('stale_cloud')
        pts=record.get('points')
        if not isinstance(pts,(list,tuple)) or not pts:return self.reject('empty_points')
        normalized=[]
        for p in pts:
            if not isinstance(p,(list,tuple)) or len(p)!=3 or not all(finite(x) for x in p):return self.reject('nonfinite_points')
            normalized.append(tuple(float(x) for x in p))
        if self.last_stamp is not None and float(stamp)<=self.last_stamp:return self.reject('nonmonotonic_stamp')
        self.last_stamp=float(stamp); self.counters['accepted']=self.counters.get('accepted',0)+1
        return {'namespace':self.namespace,'frame_id':self.frame,'acquisition_stamp':self.last_stamp,'points':normalized,'age':age,'epoch':self.epoch,'research_only':True}
