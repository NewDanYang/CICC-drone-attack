"""Read-only phase/call diagnostics, separate from physical outcome assessment."""
import argparse
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import statistics


def rows(path):return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
def stamp(row):return datetime.fromisoformat(row['wall_time']).timestamp()


def summarize(session,native=None):
    events=rows(session/'audit/events.jsonl')
    servo=[r for r in events if r.get('event')=='rosout' and r.get('message','').startswith('[VisualServo]:')]
    starts=[r for r in servo if 'Visual Servo Started' in r['message']]
    # The sealed blue policy can retry AFTER SPRINT_END, or complete through
    # BLUE_NEAR_CONTACT_LOSS_COMPLETE. Neither is a physical-hit measurement.
    stops=[r for r in servo if 'Halted, entering hover mode.' in r['message'] or
           'Sprint completed (' in r['message'] and 'SUCCESS' in r['message'] or
           'BLUE_NEAR_CONTACT_LOSS_COMPLETE ' in r['message']]
    start=starts[0] if starts else None
    stop=next((r for r in stops if start and stamp(r)>=stamp(start)),None)
    model=[]
    for path in sorted((session/'model').glob('*/audit.jsonl')):model+=rows(path)
    decisions=[r for r in model if r.get('kind')=='decision']
    initial=[r for r in decisions if r.get('mode')=='initialization']
    replays=[r for r in model if r.get('kind')=='replay']
    published=[r for r in model if r.get('kind')=='publish']
    latency={}
    for mode in ('initialization','confirmation'):
        values=sorted(r['latency_s'] for r in decisions if r['mode']==mode)
        if values:latency[mode]=dict(n=len(values),min=values[0],median=statistics.median(values),max=values[-1])
    consumed=[r for r in events if 'MULTIMODAL_PIXEL ' in r.get('message','')]
    ages=[float(m[1]) for r in consumed if (m:=re.search(r' age=([-0-9.]+)',r['message']))]
    trial=Path(native) if native is not None else Path((session/'trial_path.txt').read_text(encoding='utf-8').strip())
    planning={}
    if (trial/'planning_runs.csv').exists():
        with (trial/'planning_runs.csv').open(encoding='utf-8',newline='') as stream:
            planning={r['stage_name']:float(r['duration']) if r['duration'] else None for r in csv.DictReader(stream)}
    return dict(visual_servo_start=start['wall_time'] if start else None,
        visual_servo_stop=stop['wall_time'] if stop else None,
        visual_servo_duration_s=stamp(stop)-stamp(start) if start and stop else None,
        visual_servo_end_marker=('BLUE_NEAR_CONTACT_LOSS_COMPLETE' if 'BLUE_NEAR_CONTACT_LOSS_COMPLETE ' in stop['message']
            else 'SPRINT_SUCCESS' if 'Sprint completed (' in stop['message'] else 'Halted') if stop else None,
        sprint_start_count=sum('SPRINT_START ' in r['message'] for r in servo),
        sprint_end_count=sum('SPRINT_END ' in r['message'] for r in servo),
        sprint_success_count=sum('Sprint completed (' in r['message'] and 'SUCCESS' in r['message'] for r in servo),
        blue_near_contact_completion_count=sum('BLUE_NEAR_CONTACT_LOSS_COMPLETE ' in r['message'] for r in servo),
        blue_sprint_visible_retry_count=sum('BLUE_SPRINT_VISIBLE_RETRY ' in r['message'] for r in servo),
        target_lost_log_count=sum('Target lost. Position-held search' in r['message'] for r in servo),
        initialization_confirmation_latency_s=latency,
        initialization_decisions=dict(total=len(initial),nonempty=sum(r.get('bbox') is not None for r in initial),
            missing_model_roi=sum(r.get('model_box') is None for r in initial),
            geometry_not_confirmed=sum(r.get('model_box') is not None and r.get('bbox') is None for r in initial)),
        replay_reason_counts=dict(Counter(r.get('reason') or 'no_backend_failure' for r in replays)),
        valid_bbox_publish_messages=sum(r.get('bbox') is not None for r in published),
        invalid_publish_reason_message_counts=dict(Counter(r.get('reason') or 'no_backend_reason' for r in published if r.get('bbox') is None)),
        max_consumed_frame_age_s=max(ages) if ages else None,
        consumed_age_violations=sum(age<-.05 or age>.35 for age in ages),
        inference_errors=[r for r in model if r.get('kind')=='inference_error'],
        late_after_stop_discarded=sum(r.get('kind')=='discard_inactive' for r in model),
        planning_durations_s=planning)


def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args()
    for receipt in sorted(args.root.glob('*/driver_complete.json')):
        session=receipt.parent
        result=summarize(session)
        (session/'phase_metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(session.name,result['visual_servo_duration_s'],result['sprint_start_count'])


if __name__=='__main__':main()
