"""Offline cubic timing primitives; no vehicle interface."""
from dataclasses import dataclass
import math
class Reject(ValueError): pass
def finite(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(float(x))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def mul(a,s):return tuple(x*s for x in a)
def sub(a,b):return add(a,mul(b,-1))
def norm(a):return math.sqrt(sum(x*x for x in a))
def derivative(points,duration):return [mul(sub(b,a),(len(points)-1)/duration) for a,b in zip(points,points[1:])]
def evaluate(points,u):
    p=list(points)
    while len(p)>1:p=[add(mul(a,1-u),mul(b,u)) for a,b in zip(p,p[1:])]
    return p[0]
@dataclass
class Segment: points:list; duration:float
@dataclass
class Curve:
    segments:list
    family:str='original'
    @property
    def duration(self):return sum(s.duration for s in self.segments)
    def state(self,t,order=0):
        t=max(0,min(self.duration,t)); offset=0
        for i,s in enumerate(self.segments):
            if t<=offset+s.duration or i==len(self.segments)-1:break
            offset+=s.duration
        p=s.points
        for _ in range(order):p=derivative(p,s.duration)
        return evaluate(p,min(1,max(0,(t-offset)/s.duration)))
def validate(curve,limits=(.3,.5,4.)):
    if not curve.segments:return 'empty_curve'
    for s in curve.segments:
        if not finite(s.duration) or s.duration<=0 or len(s.points)<4:return 'invalid_segment'
        for p in s.points:
            if len(p)!=3 or not all(finite(x) for x in p):return 'invalid_segment'
        for order,cap in enumerate(limits,1):
            if max(norm(x) for x in [derivative(s.points,s.duration)] if order==1) > cap:return 'velocity_bound'
    return 'dynamics_valid'
def publication_gate(*args,**kwargs): return {'publish':False,'reasons':['offline_only_no_publication_interface']}
