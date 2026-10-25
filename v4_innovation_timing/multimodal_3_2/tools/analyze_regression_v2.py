"""Recompute matched regression rows from preserved evidence, without ROS/model.

Surviving actor colors come from postflight evaluation-only lane queries. Missing or
inconsistent mappings stay unknown and remain in the denominator.
"""
import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path
import statistics


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def analyze(session):
    complete=json.loads((session/'driver_complete.json').read_text())
    native=complete['native_row']
    snapshots=jsonl(session/'scene_snapshots.jsonl')
    before=next((r for r in snapshots if r['phase']=='before'),None)
    settled=next((r for r in snapshots if r['phase']=='settled'),None)
    mapping_path=session/'evaluation_mapping.json'
    calibration=json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    consistent=bool(before and settled and calibration and
        before['sim_pid']==settled['sim_pid']==calibration.get('after',{}).get('sim_pid') and
        set(settled['actor_ids'])==set(calibration.get('after',{}).get('actor_ids',[])))
    removed=sorted(set(before['actor_ids'])-set(settled['actor_ids'])) if before and settled else []
    colors=calibration.get('actor_to_color',{}) if consistent else {}
    target=complete['color']
    fully_mapped=bool(consistent and calibration.get('complete') and before['reported_count']==3 and
                      len(set(colors.values()))==len(colors))
    removed_colors=sorted({'red','purple','blue'}-set(colors.values())) if fully_mapped else ['unknown']*len(removed)
    physical=(target in removed_colors) if fully_mapped else (False if not removed and before and settled else None)
    extra=[color for color in removed_colors if color!=target]
    summary=complete['recognition_summary']
    row=dict(index=complete['index'],round=complete['round'],color=target,
        condition=complete['condition'],trial=complete['trial'],run_id=native['run_id'],
        total_time_s=float(native['total_time']) if native['total_time'] else None,
        end_status=native['end_status'],bt_success=native['bt_success'],
        native_mission_success=native['mission_success'],native_hit_status=native['hit_balloon_status'],
        cross_status=native['cross_frame_status'],aruco_status=native['detect_aruco_status'],
        return_status=native['return_cross_frame_status'],land_status=native['land_status'],
        boundary_events=int(native['boundary_violation_count'] or 0),
        mapping_consistent=consistent,physical_target_removed=physical,removed_actor_ids=removed,
        removed_colors=removed_colors,extra_removed_colors=extra,
        valid_decisions=summary['valid_decisions'],consumed_logs=summary['consumed_logs'],
        screenshots=summary['actual_window_screenshots'],formal_rc=(session/'formal_exit_code').read_text().strip())
    return row


def main():
    p=argparse.ArgumentParser()
    p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    rows=[analyze(path.parent) for path in sorted(args.root.glob('*/driver_complete.json'))]
    groups=defaultdict(list)
    for row in rows:groups[row['condition']].append(row)
    totals={}
    for condition,items in groups.items():
        totals[condition]=dict(n=len(items),confirmed_target_removals=sum(r['physical_target_removed'] is True for r in items),
            confirmed_misses=sum(r['physical_target_removed'] is False for r in items),
            unknown=sum(r['physical_target_removed'] is None for r in items),
            extra_removal_runs=sum(bool(r['extra_removed_colors']) for r in items),
            boundary_events=sum(r['boundary_events'] for r in items),
            median_total_s=statistics.median(r['total_time_s'] for r in items if r['total_time_s'] is not None),
            per_color={color:dict(n=sum(r['color']==color for r in items),
                confirmed_target_removals=sum(r['color']==color and r['physical_target_removed'] is True for r in items))
                for color in ('red','purple','blue')})
    result=dict(rows=rows,groups=totals,
        definition='same-instance settled Actor deletion; surviving colors queried only AFTER flight and GC',
        caution='native hit observer does not recognize new tracker; never use BT ForceSuccess as physical hit')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with args.output.with_suffix('.csv').open('w',encoding='utf-8',newline='') as stream:
        if rows:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(totals,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
