"""Post-flight GC and actor snapshots; never run while PX4 is armed."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,'/home/ubuntu/tcei_hit_balloon_v2_tools')
from scene_snapshot import snapshot,SDK,LOG


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    state=subprocess.run(['timeout','8','rostopic','echo','-n','1','/mavros/state'],
                         capture_output=True,text=True,check=True)
    if 'armed: False' not in state.stdout:
        raise RuntimeError('Post-flight GC requires confirmed disarm')
    sys.path.insert(0,SDK)
    from UE4CtrlAPI import UE4CtrlAPI
    offset=LOG.stat().st_size
    sent=datetime.now(timezone.utc).isoformat()
    UE4CtrlAPI().sendUE4Cmd('obj gc')
    time.sleep(2)
    with LOG.open('rb') as handle:
        handle.seek(offset);excerpt=handle.read().decode('utf-8','replace')
    with (args.output/'postflight_gc.json').open('w',encoding='utf-8') as stream:
        json.dump(dict(sent_at=sent,command='obj gc',state_before=state.stdout,log_excerpt=excerpt,
                       scope='after formal runner ended and PX4 disarmed; no in-flight GC'),stream,ensure_ascii=False,indent=2)
    with (args.output/'scene_snapshots.jsonl').open('a',encoding='utf-8',buffering=1) as stream:
        for phase in ('after','settled'):
            row=snapshot();row['phase']=phase
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            print(json.dumps({k:v for k,v in row.items() if k!='raw_lines'}),flush=True)
            time.sleep(3)


if __name__=='__main__': main()
