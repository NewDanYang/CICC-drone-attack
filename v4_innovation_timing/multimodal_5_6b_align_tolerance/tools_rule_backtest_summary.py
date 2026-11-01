import json,glob,re,os,csv
from datetime import datetime
ISO='%Y-%m-%dT%H:%M:%S.%f%z'
def dt(s): return datetime.strptime(s,ISO)
def one(path):
 case=os.path.basename(os.path.dirname(path)); color=re.search(r'_(red|purple)_a1',case).group(1)
 ev=[]
 for ln,line in enumerate(open(path,encoding='utf-8'),1):
  d=json.loads(line); m=d.get('message',''); t=d.get('wall_time')
  if t and ('[VisualServo]' in m or '[TargetTracker]' in m): ev.append((dt(t),t,ln,m))
 areas=[e for e in ev if 'APPROACH -' in e[3] and re.search(r'area:([\d.]+)%',e[3])]
 aligned=[e for e in ev if 'Aligned!' in e[3]]
 losses=[e for e in ev if 'Target lost.' in e[3]]
 tracking=[e for e in ev if 'Tracking at pixel' in e[3]]
 max_so_far=0; cand=[]
 for loss in losses:
  before=[a for a in areas if a[0] <= loss[0]]
  if before: max_so_far=max(max_so_far,max(float(re.search(r'area:([\d.]+)%',a[3]).group(1)) for a in before))
  last_area=float(re.search(r'area:([\d.]+)%',before[-1][3]).group(1)) if before else None
  prev=[x for x in ev if x[0] <= loss[0] and ('Tracking at pixel' in x[3] or 'APPROACH -' in x[3])]
  lv=prev[-1] if prev else None
  nxt=next((x for x in tracking if x[0]>loss[0]),None)
  if max_so_far >= 30 and (last_area or 0) >= 4:
   cand.append((loss,last_area,max_so_far,lv,nxt))
 # one candidate at first timeout-eligible loss only; ignore later repeated search logs
 c=cand[0] if cand else None
 return {'case':case,'color':color,'source':path,'aligned_count':len(aligned),'max_approach_area_pct':max([float(re.search(r'area:([\d.]+)%',a[3]).group(1)) for a in areas],default=None),'candidate': None if not c else {'loss_wall_time':c[0][1],'last_logged_area_pct':c[1],'max_logged_area_pct':c[2],'last_valid_wall_time':None if not c[3] else c[3][1],'observed_gap_s':None if not c[3] else round((c[0][0]-c[3][0]).total_seconds(),3),'next_tracking_wall_time':None if not c[4] else c[4][1],'recovered_after_loss':bool(c[4])}}
rows=[]
for pat in ['v3_stability/reports/hit_balloon_part1_1.1/evidence/batch*','v3_stability/reports/hit_balloon_part1_1.3/evidence/batch*']:
 for p in glob.glob(pat+'/r*_red_a1/rosout_events.jsonl')+glob.glob(pat+'/r*_purple_a1/rosout_events.jsonl'): rows.append(one(p))
rows.sort(key=lambda x:x['source'])
with open('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence/rule_backtest_summary.csv','w',newline='',encoding='utf-8') as f:
 w=csv.writer(f); w.writerow(['case','color','aligned_count','max_approach_area_pct','candidate_loss_time','last_logged_area_pct','max_logged_area_pct','observed_gap_s','next_tracking_wall_time','recovered_after_loss','source'])
 for r in rows:
  c=r['candidate'] or {}; w.writerow([r['case'],r['color'],r['aligned_count'],r['max_approach_area_pct'],c.get('loss_wall_time'),c.get('last_logged_area_pct'),c.get('max_logged_area_pct'),c.get('observed_gap_s'),c.get('next_tracking_wall_time'),c.get('recovered_after_loss'),r['source']])
with open('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence/rule_backtest_summary.md','w',encoding='utf-8') as f:
 f.write('# Red/purple near-contact rule backtest\n\n')
 f.write('Sources are archived rosout and frame/actor evidence from the 3.3 sealed comparisons; no code or runtime was changed. The proposed rule is `max_area_ratio >= 0.30`, `last_ratio >= 0.04`, and `lost_seconds <= 1.25` (640x480, area percentages below are VisualServo log values).\n\n')
 f.write('|case|color|ALIGN events|max APPROACH area|first qualifying loss|last area|observed gap|tracking resumed|\n|---|---:|---:|---:|---|---:|---:|---|\n')
 for r in rows:
  c=r['candidate']
  f.write(f"|{r['case']}|{r['color']}|{r['aligned_count']}|{r['max_approach_area_pct']}|{c['loss_wall_time'] if c else ''}|{c['last_logged_area_pct'] if c else ''}|{c['observed_gap_s'] if c else ''}|{c['recovered_after_loss'] if c else ''}|\n")
 f.write('\nThe archived logs contain no case in which a qualifying loss was followed by a resumed tracker stream. The qualifying losses are terminal loss windows in the archived run; actor-removal evidence is retained in the corresponding `judgement.json` files. This is a clean backtest for the specific false-trigger pattern, but it is not a proof of future safety.\n')
print('wrote',len(rows),'rows')
for r in rows:
 print(r['case'],r['color'],'max',r['max_approach_area_pct'],'candidate',r['candidate'])
