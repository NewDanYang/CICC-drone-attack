"""Offline fail-closed lifecycle watchdog; actions are labels only."""
import math
def finite(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(float(x))
class RecoveryWatchdog:
    def __init__(self,command_age=.25,state_age=1.5): self.command_age=command_age; self.state_age=state_age; self.last_mono=None; self.last_header=None; self.phase='IDLE'
    def evaluate(self,e):
        if not isinstance(e,dict) or not isinstance(e.get('kind'),str): return self.abort('invalid_event')
        mono=e.get('mono'); header=e.get('command_header_ros')
        if mono is not None and not finite(mono): return self.abort('invalid_event')
        if self.last_mono is not None and mono is not None and mono<self.last_mono:return self.abort('clock_reset')
        if mono is not None:self.last_mono=mono
        if e['kind'] in ('planner_shutdown','timeout'):return self.abort(e['kind'])
        if e['kind']=='state':
            if e.get('connected') is not True or e.get('armed') is not False or e.get('mode')!='AUTO.LOITER': return self.abort('unsafe_state')
            self.phase='MONITORING'; return self.ok('state_ok')
        if e['kind']!='sample':return self.abort('invalid_event')
        now=mono
        for key,limit,reason in [('command_receive_mono',self.command_age,'stale_command'),('odom_receive_mono',self.command_age,'stale_odometry'),('state_receive_mono',self.state_age,'stale_state')]:
            stamp=e.get(key)
            if not finite(stamp) or now-stamp<0 or now-stamp>limit:return self.abort(reason)
        if e.get('connected') is not True or e.get('armed') is not False or e.get('mode')!='AUTO.LOITER':return self.abort('unsafe_state')
        if finite(header) and self.last_header is not None and header<=self.last_header:return self.abort('duplicate_header')
        self.last_header=header; self.phase='ACTIVE'; return self.ok('sample_ok')
    def ok(self,reason): return {'action':'diagnostic_'+reason,'reason':reason,'phase':self.phase,'offline_only':True}
    def abort(self,reason): self.phase='ABORTED'; return {'action':'diagnostic_abort','reason':reason,'phase':self.phase,'offline_only':True}
