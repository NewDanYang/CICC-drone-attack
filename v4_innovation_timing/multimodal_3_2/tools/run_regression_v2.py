"""Finite, sequential 9+9 regression after reviewed three-color demos.

No flight commands are published here. Each row uses the unchanged official
trial through run_one_v2.sh, a fresh scene, and exact source/binary checks.
"""
import argparse
import csv
import ctypes
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time


def main():
    # Official sim_env_start -> kill_ros_pid.sh calls killall -9 python3.
    # Keep this non-ROS orchestration parent alive across its own scene resets.
    if ctypes.CDLL(None).prctl(15,b'tcei_mm_batch',0,0,0)!=0:
        raise RuntimeError('Cannot name orchestration process')
    parser=argparse.ArgumentParser()
    parser.add_argument('--demos',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--hours',type=float,default=4.)
    parser.add_argument('--initial-ready-log',type=Path)
    args=parser.parse_args()
    if not 0<args.hours<=4:raise ValueError('Regression budget is at most four hours')
    here=Path(__file__).resolve().parent
    root=here.parent
    manifest=root/'v2/manifest.json'
    manifest_hash=hashlib.sha256(manifest.read_bytes()).hexdigest()
    demos=json.loads(args.demos.read_text())
    if demos['package_manifest_sha256']!=manifest_hash:raise RuntimeError('Demo/candidate version mismatch')
    spec=importlib.util.spec_from_file_location('summary',here/'summarize_session_v2.py')
    summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)
    for color in ('red','purple','blue'):
        result=summary.summarize(Path(demos['sessions'][color]))
        if not all(result[key]>0 for key in ('valid_decisions','matched_decision_consumption','actual_window_screenshots')):
            raise RuntimeError('Demo chain incomplete: '+color)
    plan=[]
    for round_index in range(3):
        for color_index,color in enumerate(('red','purple','blue')):
            order=('baseline','candidate') if (round_index+color_index)%2==0 else ('candidate','baseline')
            for condition in order:
                plan.append(dict(round=round_index+1,color=color,condition=condition))
    args.output.mkdir(parents=True,exist_ok=True)
    plan_file=args.output/'plan.json'
    scripts=('run_regression_v2.py','calibrate_scene_evaluation_v2.py','analyze_regression_v2.py')
    orchestration={name:hashlib.sha256((here/name).read_bytes()).hexdigest() for name in scripts}
    configuration=dict(plan=plan,package_manifest_sha256=manifest_hash,demos=demos,budget_hours=args.hours,
                       orchestration_sha256=orchestration,initial_ready_log=str(args.initial_ready_log) if args.initial_ready_log else None)
    if plan_file.exists():
        previous=json.loads(plan_file.read_text())
        if any(previous.get(key)!=value for key,value in configuration.items()):raise RuntimeError('Existing plan differs')
        configuration=previous
    else:
        configuration.update(started_at=time.time(),deadline_epoch=time.time()+args.hours*3600)
        plan_file.write_text(json.dumps(configuration,ensure_ascii=False,indent=2))
    progress=(args.output/'progress.jsonl').open('a',encoding='utf-8',buffering=1)
    def record(phase,**fields):
        value=dict(time=datetime.now(timezone.utc).isoformat(),phase=phase,**fields)
        progress.write(json.dumps(value,ensure_ascii=False)+'\n');print(json.dumps(value,ensure_ascii=False),flush=True)
    def run(command,log):
        with log.open('w') as stream:subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
    for index,item in enumerate(plan):
        session=args.output/f'{index+1:02d}_r{item["round"]}_{item["color"]}_{item["condition"]}'
        if (session/'driver_complete.json').exists():record('already_complete',index=index+1,session=str(session));continue
        if session.exists():raise RuntimeError('Inspect partial session before resuming: '+str(session))
        if time.time()>=configuration['deadline_epoch']:
            record('budget_stop',next_index=index+1)
            run(['bash',str(here/'switch_condition_v2.sh'),'baseline',str(args.backup)],args.output/'budget_rollback.log')
            return
        record('switching',index=index+1,**item)
        log=args.output/f'{index+1:02d}_switch.log'
        if index==0 and args.initial_ready_log:
            log.write_bytes(args.initial_ready_log.read_bytes())
            record('reuse_own_unflown_ready_scene',index=1,source_log=str(args.initial_ready_log))
        else:
            run(['bash',str(here/'switch_condition_v2.sh'),item['condition'],str(args.backup)],log)
        if 'environment_started=1' not in log.read_text(errors='replace'):raise RuntimeError('Environment not ready')
        receipt=subprocess.check_output(['/usr/bin/python3',str(root/'patches/deploy_v2.py'),'status',str(args.backup)],text=True)
        activation=json.loads(receipt)
        if activation['mode']!=item['condition']:raise RuntimeError('Condition mismatch')
        binary=Path('/home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros').read_bytes()
        tag=b'<MultimodalTargetTracker object_name'
        if (tag in binary)!=(item['condition']=='candidate'):raise RuntimeError('Stale BT binary')
        if hashlib.sha256(manifest.read_bytes()).hexdigest()!=manifest_hash:raise RuntimeError('Frozen package changed')
        planner={name:subprocess.check_output(['rosparam','get',name],text=True).strip() for name in
                 ('/ego_planner_node/manager/max_vel','/ego_planner_node/optimization/max_vel')}
        record('running',index=index+1,session=str(session),**item)
        run(['bash',str(here/'run_one_v2.sh'),item['color'],item['condition'],str(session)],args.output/f'{index+1:02d}_trial.log')
        calibration=session/'evaluation_mapping.json'
        record('postflight_mapping',index=index+1)
        run(['/usr/bin/python3',str(here/'calibrate_scene_evaluation_v2.py'),str(calibration),'--session',str(session)],
            args.output/f'{index+1:02d}_mapping.log')
        (session/'source_receipt.json').write_text(receipt)
        (session/'planner_params.json').write_text(json.dumps(planner,indent=2))
        data=summary.summarize(session)
        trial=Path((session/'trial_path.txt').read_text().strip())
        match=re.search(r'^run_id=(.+)$',(trial/'observer.out').read_text(errors='replace'),re.M)
        if not match:raise RuntimeError('Observer run ID missing')
        with Path('/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv').open(newline='') as stream:
            native=next(row for row in csv.DictReader(stream) if row['run_id']==match[1].strip())
        if native['target_color']!=item['color']:raise RuntimeError('Native trial color mismatch')
        completed=dict(item,index=index+1,trial=str(trial),native_row=native,recognition_summary=data)
        (session/'driver_complete.json').write_text(json.dumps(completed,ensure_ascii=False,indent=2))
        record('complete',index=index+1,trial=str(trial),consumed=data['consumed_logs'],screenshots=data['actual_window_screenshots'])
    record('restoring_baseline')
    run(['bash',str(here/'switch_condition_v2.sh'),'baseline',str(args.backup)],args.output/'final_rollback.log')
    record('regression_complete',planned_runs=len(plan))


if __name__=='__main__':main()
