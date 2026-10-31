"""Summarize every case; never count an unchanged fallback as an improvement."""
import argparse
import csv
import json
import statistics
from pathlib import Path

def summarize(directory):
    rows=list(csv.DictReader((directory/'replanning_benchmark.csv').open()))
    solved=[r for r in rows if r['success']=='1']
    selected=[r for r in solved if r['guarded_accepted']=='1']
    gains=[100*(1-float(r['guarded_s'])/float(r['original_s'])) for r in solved]
    return {
        'scope':'synthetic maps and states; unchanged official EGO solver; offline, not flight',
        'total_cases':len(rows),'original_solver_returned_trajectory':len(solved),
        'original_failures_preserved':len(rows)-len(solved),
        'ungated_selected':sum(r['ungated_accepted']=='1' for r in solved),
        'smoothness_guard_selected':len(selected),
        'fallback_trajectories':len(solved)-len(selected),
        'all_solved_case_median_time_reduction_percent':statistics.median(gains),
        'all_solved_case_mean_time_reduction_percent':statistics.mean(gains),
        'selected_cases':[dict(r,
            time_reduction_percent=100*(1-float(r['guarded_s'])/float(r['original_s'])),
            sampled_jerk_rms_reduction_percent=100*(1-float(r['guarded_jerk_sampled'])/float(r['original_jerk_sampled']))) for r in selected],
        'map_groups':{str(m):{'cases':sum(r['map']==str(m) for r in rows),
            'selected':sum(r['map']==str(m) for r in selected)} for m in range(3)},
        'new_flights':0,'recommended_for_competition':False,
        'runtime_version_verified':False,
        'acceptance':'research candidate only; missing live known-free map and full flight verification'}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('directory',type=Path)
    args=ap.parse_args();print(json.dumps(summarize(args.directory),indent=2))
