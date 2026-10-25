"""Evaluation ONLY: map this UE instance's actor IDs to measured lanes.

No result is published to ROS or read by perception/control. Query ONLY surviving
actors after the completed flight and GC; reset the whole UE before another run.
Preflight actor payload requests followed by destruction/GC can crash the SDK.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=15.)
    args=parser.parse_args()
    if not 10<=args.seconds<=45:raise ValueError('Postflight window must be 10-45 seconds')
    if Path('/tmp/tcei_formal_trial.lock').exists():raise RuntimeError('Formal trial active')
    state=subprocess.check_output(['rostopic','echo','-n','1','/mavros/state'],text=True,timeout=10)
    if 'armed: False' not in state:raise RuntimeError('Disarmed simulator required')
    sys.path.insert(0,'/home/ubuntu/tcei_hit_balloon_v2_tools')
    from scene_snapshot import SDK,snapshot
    sys.path.insert(0,SDK)
    from UE4CtrlAPI import UE4CtrlAPI
    snapshots=[json.loads(line) for line in (args.session/'scene_snapshots.jsonl').read_text().splitlines()]
    settled=next(row for row in snapshots if row['phase']=='settled')
    if not (args.session/'postflight_gc.json').exists():raise RuntimeError('Postflight GC receipt missing')
    before=snapshot()
    if before['sim_pid']!=settled['sim_pid'] or before['actor_ids']!=settled['actor_ids']:
        raise RuntimeError('Postflight roster changed')
    responses={};requests=[]
    api=UE4CtrlAPI();api.initUE4MsgRec();time.sleep(.3)
    deadline=time.monotonic()+args.seconds;index=0
    try:
        while time.monotonic()<deadline:
            if not before['actor_ids']:break
            actor=before['actor_ids'][index%len(before['actor_ids'])];index+=1
            api.reqObj([actor])
            requests.append(dict(time=datetime.now(timezone.utc).isoformat(),actor=actor))
            time.sleep(.25)
            for name in before['actor_ids']:
                obj=api.getCamCoptObj(type_id=2,objName=name)
                if obj!=0:
                    responses[name]=dict(name=str(obj.ObjName),position_ue=[float(v) for v in obj.PosUE],
                        ue_timestamp=float(obj.timestmp),received_at=datetime.now(timezone.utc).isoformat())
    finally:
        api.stopFlagUE4=True
        api.udp_socket.sendto(b'\0',('127.0.0.1',20006))
        api.t4.join(timeout=2);api.udp_socketUE4.close()
    after=snapshot()
    if before['sim_pid']!=after['sim_pid'] or before['actor_ids']!=after['actor_ids']:
        raise RuntimeError('Scene changed during evaluation calibration')
    mapping={};provenance={}
    for actor,response in responses.items():
        x,y,z=response['position_ue']
        color='red' if abs(y-2.1)<.05 else 'purple' if abs(y+2.1)<.05 else 'blue' if abs(x-5.6)<.05 else None
        if color:
            mapping[actor]=color;provenance[actor]='measured_current_instance_lane'
    if len(set(mapping.values()))!=len(mapping):raise RuntimeError('Ambiguous lane assignment')
    result=dict(usage='evaluation_only_never_control',fixed_window_seconds=args.seconds,
                timing='surviving actors only, AFTER flight, disarm, GC and settled roster; reset UE before next run',
                before=before,after=after,responses=responses,requests=requests,
                actor_to_color=mapping,provenance=provenance,complete=len(mapping)==len(before['actor_ids']),
                color_source='ChallengeMap fixed lane/color association verified in hit_balloon_part1_boundary_survey; not an SDK color property',
                lane_reference=dict(red_y=2.1,purple_y=-2.1,blue_x=5.6,tolerance_m=.05))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(args.output),complete=result['complete'],mapping=mapping),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
