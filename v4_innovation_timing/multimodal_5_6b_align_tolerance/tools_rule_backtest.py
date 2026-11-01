#!/usr/bin/env python3
import csv, json, re, glob, os
from datetime import datetime

ROOTS = [
    'v3_stability/reports/hit_balloon_part1_1.1/evidence/batch*',
    'v3_stability/reports/hit_balloon_part1_1.3/evidence/batch*',
]

ISO = '%Y-%m-%dT%H:%M:%S.%f%z'
def parse_t(s):
    return datetime.strptime(s, ISO)

def case_rows(path):
    case = os.path.basename(os.path.dirname(path))
    color = re.search(r'_(red|purple)_a1', case).group(1)
    ev = []
    for ln, line in enumerate(open(path, encoding='utf-8'), 1):
        d = json.loads(line); msg=d.get('message',''); t=d.get('wall_time')
        if not t: continue
        if any(x in msg for x in ('[VisualServo]', '[TargetTracker]')):
            ev.append({'line':ln,'t':t,'dt':parse_t(t),'msg':msg})
    areas=[]; aligned=[]; sprint=[]; losses=[]; tracking=[]
    for e in ev:
        m=e['msg']
        if 'APPROACH -' in m:
            q=re.search(r'area:([0-9.]+)%',m)
            if q:
                e['area_pct']=float(q.group(1)); areas.append(e)
        if 'Aligned!' in m: aligned.append(e)
        if 'SPRINT_START' in m: sprint.append(e)
        if 'Target lost.' in m: losses.append(e)
        if 'Tracking at pixel' in m: tracking.append(e)
    max_area=0.0
    qual=[]
    for loss in losses:
        prior_area=[a for a in areas if a['dt'] <= loss['dt']]
        if prior_area: max_area=max(max_area,max(a['area_pct'] for a in prior_area))
        # Last tracker/approach record before this loss. The branch itself fires only after data_timeout.
        prior_valid=[x for x in ev if x['dt'] <= loss['dt'] and ('Tracking at pixel' in x['msg'] or 'APPROACH -' in x['msg'])]
        last_valid=prior_valid[-1] if prior_valid else None
        next_tracking=next((x for x in tracking if x['dt'] > loss['dt']),None)
        recover_s=(next_tracking['dt']-loss['dt']).total_seconds() if next_tracking else None
        last_area=last_area_raw=None
        if prior_area:
            last_area_raw=prior_area[-1]; last_area=last_area_raw['area_pct']
        # Candidate rule uses max_area_ratio >= .30 and last_ratio >= .04; the log is in percent.
        candidate = max_area >= 30.0 and (last_area is not None and last_area >= 4.0)
        qual.append({
            'loss_wall_time':loss['t'],
            'loss_line':loss['line'],
            'last_logged_area_pct':last_area,
            'max_logged_area_pct':max_area,
            'last_valid_wall_time': last_valid['t'] if last_valid else None,
            'observed_gap_since_last_valid_s': (loss['dt']-last_valid['dt']).total_seconds() if last_valid else None,
            'rule_candidate_at_loss':candidate,
            'next_tracking_wall_time': next_tracking['t'] if next_tracking else None,
            'recovery_after_loss_s': recover_s,
            'recovered_within_10s': recover_s is not None and recover_s <= 10,
        })
    return {
        'case':case,'color':color,'path':path,
        'aligned_count':len(aligned),'sprint_count':len(sprint),
        'approach_log_count':len(areas),'max_approach_area_pct':max([a['area_pct'] for a in areas], default=None),
        'loss_count':len(losses), 'qualifying_loss_count':sum(q['rule_candidate_at_loss'] for q in qual),
        'false_positive_recovery_count':sum(q['rule_candidate_at_loss'] and q['recovered_within_10s'] for q in qual),
        'losses':qual,
    }

out=[]
for pattern in ROOTS:
    for p in glob.glob(pattern+'/r*_red_a1/rosout_events.jsonl')+glob.glob(pattern+'/r*_purple_a1/rosout_events.jsonl'):
        out.append(case_rows(p))
out.sort(key=lambda x:x['path'])
os.makedirs('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence',exist_ok=True)
with open('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence/rule_backtest.json','w',encoding='utf-8') as f: json.dump(out,f,ensure_ascii=False,indent=2)
with open('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence/rule_backtest.csv','w',newline='',encoding='utf-8') as f:
    w=csv.writer(f); w.writerow(['case','color','aligned_count','sprint_count','approach_log_count','max_approach_area_pct','loss_count','qualifying_loss_count','false_positive_recovery_count','source'])
    for r in out: w.writerow([r[k] for k in ['case','color','aligned_count','sprint_count','approach_log_count','max_approach_area_pct','loss_count','qualifying_loss_count','false_positive_recovery_count','path']])
print('case,color,aligned,max_area_pct,losses,qualifying,recovery')
for r in out:
 print(r['case'],r['color'],r['aligned_count'],r['max_approach_area_pct'],r['loss_count'],r['qualifying_loss_count'],r['false_positive_recovery_count'])
 for q in r['losses']:
  if q['rule_candidate_at_loss']:
   print('  candidate',q)
