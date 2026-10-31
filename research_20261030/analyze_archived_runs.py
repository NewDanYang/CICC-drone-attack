"""Recompute frozen timings from raw observer outputs; never treat BT as a hit."""
import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics
import tarfile

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('repo',type=Path);ap.add_argument('out',type=Path)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    archive=a.repo/'v3_stability/reports/hit_balloon_part1_1.8/evidence/batch5_evidence.tar.gz'
    rows=[];detail=[]
    with tarfile.open(archive) as tar:
        for name in sorted(n for n in tar.getnames() if n.endswith('/observer.out')):
            text=tar.extractfile(name).read().decode('utf-8',errors='replace')
            summary=json.JSONDecoder().raw_decode(text[text.index('\n{')+1:])[0]
            prefix=name.rsplit('/',1)[0]
            events=[json.loads(line) for line in tar.extractfile(prefix+'/rosout_events.jsonl').read().decode().splitlines()]
            planning=[];start=None;offboard=[];servo=[]
            for e in events:
                msg=e.get('message','');t=dt.datetime.fromisoformat(e['wall_time'])
                if msg.startswith('[PlanningControl]') and 'Planning navigation start' in msg:start=t
                if msg.startswith('[PlanningControl]') and 'Planning navigation completed' in msg and start:
                    planning.append((t-start).total_seconds());start=None
                if msg.startswith('[Takeoff]') and 'Requesting mode OFFBOARD' in msg:offboard.append(e['wall_time'])
                if msg.startswith('[VisualServo]'):servo.append({'time':e['wall_time'],'message':msg})
            row={'trial':prefix,'color':summary['target_color'],'total_s':float(summary['total_time']),
                 'bt_success':summary['bt_success'],'observer_mission_success':summary['mission_success'],
                 'observer_hit_status':summary['hit_balloon_status'],
                 'boundary_events':int(summary['boundary_violation_count']),
                 'planning_count':len(planning),'planning_total_s':sum(planning)}
            for i,duration in enumerate(planning):row['planning_'+str(i+1)+'_s']=duration
            rows.append(row);detail.append({'trial':prefix,'offboard_requests':offboard,'visual_servo_events':servo,'observer':summary})
    medians={c:statistics.median(r['total_s'] for r in rows if r['color']==c) for c in ('red','purple','blue')}
    summary={'kind':'reanalysis_of_historical_flight_not_new_flight','n':len(rows),
        'source':str(archive.relative_to(a.repo)), 'source_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'median_total_s':statistics.median(r['total_s'] for r in rows),'color_medians_s':medians,
        'user_required_reference_s':{'overall':105.594,'red':133.990,'purple':105.594,'blue':98.896},
        'user_required_targets_120pct_s':{'overall':126.7128,'red':160.788,'purple':126.7128,'blue':118.6752},
        'baseline_discrepancy':'This archived batch is NOT the user-specified 105.594s reference. Do not replace the acceptance target with this batch.',
        'bt_success_count':sum(r['bt_success']=='true' for r in rows),
        'observer_mission_success_count':sum(r['observer_mission_success']=='true' for r in rows),
        'physical_hit_count_from_published_frame_review':8,
        'physical_hit_note':'8/9 is the historical report frame review, not inferred anew from SUCCESS or Actor count.',
        'recent_report_only':[{'color':'purple','total_s':141.199,'physical':'reported miss'},
            {'color':'blue','total_s':141.652,'physical':'human reported hit; automatic evidence inconsistent'},
            {'color':'red','total_s':216.383,'physical':'invalid complete comparison: missing cross_frame'}]}
    (a.out/'historical_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (a.out/'historical_events.json').write_text(json.dumps(detail,indent=2,ensure_ascii=False),encoding='utf-8')
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (a.out/'historical_runs.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
