"""Offline reanalysis of archived 3.3 rows, no ROS/model/server required.

Uses raw same-instance actor rosters and postflight surviving-actor lane queries.
Unknown targets remain in the denominator. Unknown removed colors alone cannot
prove collateral; two removals guarantee at least one extra removed actor.
"""
import argparse
import csv
from collections import Counter,defaultdict
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import statistics
import tarfile
import tempfile


def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def text(path):return path.read_text(encoding='utf-8')
def jsonl(path):return [json.loads(line) for line in text(path).splitlines()]


def physical_outcome(session,target,native):
    snapshots=jsonl(session/'scene_snapshots.jsonl')
    before=next((r for r in snapshots if r['phase']=='before'),None)
    settled=next((r for r in snapshots if r['phase']=='settled'),None)
    valid=bool(before and settled and before['sim_pid']==settled['sim_pid'] and
        before['reported_count']==len(before['actor_ids'])==3 and
        settled['reported_count']==len(settled['actor_ids']) and
        set(settled['actor_ids'])<=set(before['actor_ids']))
    def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    try:
        gc=json.loads(text(session/'postflight_gc.json'))
        ordered=(stamp(before['wall_time'])<=stamp(native['start_time'])<=stamp(native['end_time'])<=
                 stamp(gc['sent_at'])<=stamp(settled['wall_time']))
    except (OSError,KeyError,TypeError,ValueError):ordered=False
    valid=bool(valid and ordered)
    removed=sorted(set(before['actor_ids'])-set(settled['actor_ids'])) if valid else []
    path=session/'evaluation_mapping.json'
    mapping=json.loads(text(path)) if path.exists() else {}
    colors=mapping.get('actor_to_color',{})
    mapped=bool(valid and mapping.get('after',{}).get('sim_pid')==settled['sim_pid'] and
        set(mapping.get('after',{}).get('actor_ids',[]))==set(settled['actor_ids']) and
        set(colors)<=set(settled['actor_ids']) and
        set(colors.values())<={'red','purple','blue'} and len(set(colors.values()))==len(colors))
    if mapped:
        try:mapped=(stamp(settled['wall_time'])<=stamp(mapping['before']['wall_time'])<=stamp(mapping['after']['wall_time']))
        except (KeyError,TypeError,ValueError):mapped=False
    if not mapped:colors={}
    complete=bool(mapped and set(colors)==set(settled['actor_ids']))
    if valid and not removed:hit=False
    elif target in colors.values():hit=False
    elif complete:hit=True
    else:hit=None
    removed_colors=sorted({'red','purple','blue'}-set(colors.values())) if complete else ['unknown']*len(removed)
    extra_min=max(0,len(removed)-(0 if hit is False else 1)) if valid else None
    return dict(physical_target_removed=hit,same_instance_roster_valid=valid,
        flight_gc_roster_time_order_valid=ordered,
        surviving_color_mapping_complete=complete,removed_actor_ids=removed,removed_colors=removed_colors,
        extra_removed_minimum=extra_min,confirmed_extra_removal=bool(extra_min is not None and extra_min>0),
        scene_before_count=before['reported_count'] if before else None,
        scene_after_count=settled['reported_count'] if settled else None)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('archives',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--require-complete',action='store_true',help='Require the original balanced 18-row sequence')
    args=parser.parse_args()
    summary=module('session_summary','summarize_session_v2.py')
    phases=module('phase_summary','summarize_flight_phases_v2.py')
    results=[]
    for path in sorted(args.archives.glob('*.tar.gz')):
        with tarfile.open(path) as archive,tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            metadata=json.load(archive.extractfile('MANIFEST.json'))
            for member in archive.getmembers():
                wanted=(member.name.startswith('session/') and
                    (member.name.endswith(('.json','.jsonl')) or member.name.endswith('/formal_exit_code') or
                     member.name.startswith('session/audit/screenshots/') and member.name.endswith('.png')) or
                    member.name=='native/planning_runs.csv')
                if not wanted or not member.isfile():continue
                target=(root/member.name).resolve()
                if root.resolve() not in target.parents:raise ValueError('Unsafe archive path')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
            session=root/'session'
            complete=json.loads(text(session/'driver_complete.json'));native=complete['native_row']
            activation=json.loads(text(session/'source_receipt.json'))
            expected_entry={'baseline':'fca24bf1142ca8cddfb9e8d39c387a43','candidate':'de03cd1a5687f7bc0664ea52f3cd095f'}
            expected_bt={'baseline':'9b1cefe9dfa431418435f7f8f63a60ed','candidate':'9a1e8d2a5913968b1c2300cad1dc02f7'}
            condition=complete['condition']
            if (activation['mode']!=condition or activation['mission_md5']!=expected_entry[condition] or
                    activation['bt_md5']!=expected_bt[condition]):raise ValueError('Wrong source condition: '+path.name)
            if bool(activation['plugin_md5'])!=(condition=='candidate'):raise ValueError('Wrong plugin presence: '+path.name)
            planner=json.loads(text(session/'planner_params.json'))
            if set(planner.values())!={'0.35'}:raise ValueError('Planner speed differs: '+path.name)
            actual=summary.summarize(session)
            # Recompute counts and real nonblank screenshots, do not trust the driver summary alone.
            for name in ('valid_decisions','consumed_logs','matched_decision_consumption','actual_window_screenshots'):
                if actual[name]!=complete['recognition_summary'][name]:raise ValueError('Summary differs: '+path.name+' '+name)
            row=dict(index=complete['index'],round=complete['round'],color=complete['color'],
                condition=complete['condition'],archive=path.name,server_session=metadata['server_session'],
                trial=complete['trial'],native_run_id=native['run_id'],
                total_time_s=float(native['total_time']) if native['total_time'] else None,
                end_status=native['end_status'],native_bt_success=native['bt_success'],
                native_mission_success=native['mission_success'],native_hit_status=native['hit_balloon_status'],
                native_failure_stage=native['failure_stage'],native_failure_reason=native['failure_reason'],
                aruco_status=native['detect_aruco_status'],boundary_events=int(native['boundary_violation_count'] or 0),
                valid_decisions=actual['valid_decisions'],consumed_logs=actual['consumed_logs'],
                matched_decision_consumption=actual['matched_decision_consumption'],
                actual_window_screenshots=actual['actual_window_screenshots'],
                processor_items=actual['processor_items'],model_calls=actual['model_calls'],
                source_frames=actual['sources'],
                processor_image_count_violations=actual['image_count_violations'],
                source_condition_validated=True,bt_binary_md5=activation['binary_md5'],
                plugin_md5=activation['plugin_md5'],planner_params=planner,
                formal_rc=text(session/'formal_exit_code').strip())
            row.update(physical_outcome(session,row['color'],native))
            row['phase_metrics']=phases.summarize(session,root/'native')
            results.append(row)
    results.sort(key=lambda r:r['index'])
    if args.require_complete:
        expected=[]
        for round_index in range(3):
            for color_index,color in enumerate(('red','purple','blue')):
                order=('baseline','candidate') if (round_index+color_index)%2==0 else ('candidate','baseline')
                expected.extend((round_index+1,color,condition) for condition in order)
        if len(results)!=18 or [r['index'] for r in results]!=list(range(1,19)):
            raise ValueError('The original 18 rows are not all present')
        if [(r['round'],r['color'],r['condition']) for r in results]!=expected:
            raise ValueError('The original fixed order differs')
    groups=defaultdict(list)
    for row in results:groups[row['condition']].append(row)
    totals={}
    for condition,items in groups.items():
        durations=[r['total_time_s'] for r in items if r['total_time_s'] is not None]
        totals[condition]=dict(n=len(items),confirmed_hits=sum(r['physical_target_removed'] is True for r in items),
            confirmed_misses=sum(r['physical_target_removed'] is False for r in items),
            unknown=sum(r['physical_target_removed'] is None for r in items),
            confirmed_extra_removal_runs=sum(r['confirmed_extra_removal'] for r in items),
            boundary_events=sum(r['boundary_events'] for r in items),
            min_total_s=min(durations),median_total_s=statistics.median(durations),max_total_s=max(durations),
            reached_servo=sum(r['phase_metrics']['visual_servo_start'] is not None for r in items),
            sprint_runs=sum(r['phase_metrics']['sprint_start_count']>0 for r in items),
            model_consumption_runs=sum(r['consumed_logs']>0 for r in items),
            inference_error_count=sum(len(r['phase_metrics']['inference_errors']) for r in items),
            per_color={color:dict(n=sum(r['color']==color for r in items),
                hits=sum(r['color']==color and r['physical_target_removed'] is True for r in items),
                unknown=sum(r['color']==color and r['physical_target_removed'] is None for r in items))
                for color in ('red','purple','blue')})
    result=dict(rows=results,groups=totals,
        complete_original_protocol=bool(args.require_complete),
        physical_definition='target-color Actor deletion proxy, not official scoring; same-instance postflight GC roster; surviving colors measured after flight; never used by control',
        unknown_rule='unknown remains in denominator; an unknown single removal is not automatically collateral')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    flat=[{k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()} for row in results]
    if flat:
        with args.output.with_suffix('.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    print(json.dumps(totals,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
