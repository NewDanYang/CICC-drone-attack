"""Finish the confirmed unstarted sixth row, then resume the frozen driver.

The VM stopped during its build, not during a flight. Preserve the interruption
and exclude only the observed server outage from the four-hour work budget.
No perception, flight, protocol thresholds or planned rows are changed.
"""
import csv
import ctypes
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def main():
    if ctypes.CDLL(None).prctl(15,b'tcei_mm_batch',0,0,0)!=0:raise RuntimeError('Cannot name resume process')
    here=Path(__file__).resolve().parent;root=here.parent
    batch=Path('/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026')
    backup=Path('/home/ubuntu/multimodal_v2_backup_20261026T0009')
    plan_file=batch/'plan.json';plan=json.loads(plan_file.read_text())
    manifest=root/'v2/manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=plan['package_manifest_sha256']:
        raise RuntimeError('Frozen candidate changed')
    for name,expected in plan['orchestration_sha256'].items():
        if hashlib.sha256((here/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Original orchestration changed: '+name)
    for index,item in enumerate(plan['plan'][:5]):
        previous=batch/f'{index+1:02d}_r{item["round"]}_{item["color"]}_{item["condition"]}'
        if not (previous/'driver_complete.json').exists():raise RuntimeError('Earlier row incomplete')
    item=plan['plan'][5]
    if item!=dict(round=1,color='blue',condition='candidate'):raise RuntimeError('Unexpected sixth row')
    session=batch/'06_r1_blue_candidate'
    if session.exists():raise RuntimeError('Do not overwrite an attempted row')
    ready=Path('/tmp/mm_v2_resume_bootstrap.log')
    if 'environment_started=1' not in ready.read_text():raise RuntimeError('Resume startup incomplete')
    if not (batch/'06_switch.interrupted_20261026T1806.log').exists():raise RuntimeError('Interruption log missing')
    if not (batch/'plan.before_resume_20261026.json').exists():
        shutil.copy2(plan_file,batch/'plan.before_resume_20261026.json')
    pause_start=datetime.fromisoformat('2026-10-25T20:09:39.813008+00:00').timestamp()
    pause_end=datetime.fromisoformat('2026-10-26T10:06:33+00:00').timestamp()
    if plan.get('budget_pauses'):raise RuntimeError('Budget pause already applied; inspect before retry')
    old_deadline=plan['deadline_epoch']
    plan['budget_pauses']=[dict(reason='SSH unavailable then user-confirmed VM restart; sixth build interrupted before flight',
        observed_unavailable_at=pause_start,reconnected_at=pause_end,excluded_seconds=pause_end-pause_start,
        applied_at=time.time(),resume_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())]
    overall=datetime.fromisoformat('2026-10-28T23:05:00+08:00').timestamp()
    plan['deadline_epoch']=min(old_deadline+pause_end-pause_start,overall)
    plan_file.write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    with (batch/'progress.jsonl').open('a',encoding='utf-8',buffering=1) as progress:
        def record(phase,**fields):
            row=dict(time=datetime.now(timezone.utc).isoformat(),phase=phase,**fields)
            progress.write(json.dumps(row,ensure_ascii=False)+'\n');print(json.dumps(row,ensure_ascii=False),flush=True)
        def run(command,log):
            with log.open('w') as stream:subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
        record('resume_after_reboot',completed_rows=5,next_index=6,old_deadline=old_deadline,
               new_deadline=plan['deadline_epoch'],flight_interrupted=False)
        (batch/'06_switch.log').write_bytes(ready.read_bytes())
        receipt=subprocess.check_output(['/usr/bin/python3',str(root/'patches/deploy_v2.py'),'status',str(backup)],text=True)
        if json.loads(receipt)['mode']!='candidate':raise RuntimeError('Candidate not active')
        if b'<MultimodalTargetTracker object_name' not in Path('/home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros').read_bytes():
            raise RuntimeError('BT binary mismatch')
        planner={name:subprocess.check_output(['rosparam','get',name],text=True).strip() for name in
            ('/ego_planner_node/manager/max_vel','/ego_planner_node/optimization/max_vel')}
        record('running',index=6,session=str(session),**item)
        run(['bash',str(here/'run_one_v2.sh'),'blue','candidate',str(session)],batch/'06_trial.log')
        record('postflight_mapping',index=6)
        run(['/usr/bin/python3',str(here/'calibrate_scene_evaluation_v2.py'),str(session/'evaluation_mapping.json'),
             '--session',str(session)],batch/'06_mapping.log')
        (session/'source_receipt.json').write_text(receipt)
        (session/'planner_params.json').write_text(json.dumps(planner,indent=2))
        spec=importlib.util.spec_from_file_location('summary',here/'summarize_session_v2.py')
        summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)
        data=summary.summarize(session)
        trial=Path((session/'trial_path.txt').read_text().strip())
        match=re.search(r'^run_id=(.+)$',(trial/'observer.out').read_text(errors='replace'),re.M)
        if not match:raise RuntimeError('Run ID missing')
        with Path('/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv').open(newline='') as stream:
            native=next(row for row in csv.DictReader(stream) if row['run_id']==match[1].strip())
        if native['target_color']!='blue':raise RuntimeError('Native color mismatch')
        complete=dict(item,index=6,trial=str(trial),native_row=native,recognition_summary=data)
        (session/'driver_complete.json').write_text(json.dumps(complete,ensure_ascii=False,indent=2))
        record('complete',index=6,trial=str(trial),consumed=data['consumed_logs'],screenshots=data['actual_window_screenshots'])
    os.execv('/usr/bin/python3',['/usr/bin/python3','-u',str(here/'run_regression_v2.py'),
        '--demos',str(root/'demo_review.json'),'--backup',str(backup),'--output',str(batch),'--hours','4',
        '--initial-ready-log','/home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_startup_aborted_20261026/01_switch.log'])


if __name__=='__main__':main()
