#!/usr/bin/env python3
"""Summarize every completed variance replay without dropping raw trial values."""
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT_JSON = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'summary.json'
OUT_MD = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'REPORT_TABLES.md'
THRESHOLDS = {'red': 68.0, 'purple': 51.0, 'blue': 62.0}


def percentile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))]


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


trials = []
for path in sorted((ROOT / 'rounds').glob('*.json')):
    data = json.loads(path.read_text())
    if isinstance(data, dict) and 'status' in data and data.get('status') == 'crashed':
        trials.append({'source': path.name, **data})
        continue
    for key, value in data.items():
        if isinstance(value, dict):
            trials.append({'source': path.name, 'key': key, **value})

core = [t for t in trials if str(t.get('label', '')).startswith('round0')]
extra = [t for t in trials if t not in core]
by_color = defaultdict(list)
by_run = defaultdict(list)
for trial in core:
    run = trial.get('run', '')
    parts = run.split('_')
    color = parts[2] if len(parts) > 2 else 'unknown'
    trial['color'] = color
    by_color[color].append(trial)
    by_run[run].append(trial)
for trial in extra:
    run = trial.get('run', '')
    parts = run.split('_')
    trial['color'] = parts[2] if len(parts) > 2 else 'unknown'

color_summary = {}
for color in ('red', 'purple', 'blue'):
    values = [t.get('centre_pct') for t in by_color[color]]
    valid_values = [v for v in values if v is not None]
    color_summary[color] = {
        'count': len(values),
        'all_centre_pct': values,
        'valid_count': len(valid_values),
        'no_data_count': len(values) - len(valid_values),
        'median_centre_pct': median(valid_values),
        'worst_centre_pct': min(valid_values) if valid_values else None,
        'best_centre_pct': max(valid_values) if valid_values else None,
        'median_threshold_pct': THRESHOLDS[color],
        'median_pass': bool(valid_values) and median(valid_values) >= THRESHOLDS[color],
        'worst_pass': bool(valid_values) and min(valid_values) >= 30.0,
        'runs': {
            run: [t.get('centre_pct') for t in by_run[run]]
            for run in sorted(by_run)
            if run.split('_')[2] == color
        },
    }

order_comparison = {}
for run, items in sorted(by_run.items()):
    canonical = next((t for t in items if t.get('label') == 'round01_canonical'), None)
    shuffled = [t for t in items if str(t.get('label', '')).startswith('round0') and t.get('label') != 'round01_canonical']
    if canonical and shuffled:
        base = canonical.get('centre_pct')
        vals = [t.get('centre_pct') for t in shuffled]
        order_comparison[run] = {
            'canonical_centre_pct': base,
            'shuffled_centre_pct': vals,
            'shuffled_minus_canonical': [None if v is None or base is None else round(v - base, 3) for v in vals],
            'shuffled_median_minus_canonical': None if base is None else round(median(vals) - base, 3),
        }

gpu_by_stage = defaultdict(list)
for trial in core:
    for stage, stats in (trial.get('gpu_ms_stats') or {}).items():
        if stats.get('median') is not None:
            gpu_by_stage[stage].append({'key': trial.get('key'), 'run': trial.get('run'),
                                        'label': trial.get('label'), 'centre_pct': trial.get('centre_pct'),
                                        'median_ms': stats.get('median'), 'p95_ms': stats.get('p95'),
                                        'max_ms': stats.get('max'), 'count': stats.get('count')})

gpu_summary = {}
for stage, rows in sorted(gpu_by_stage.items()):
    medians = [r['median_ms'] for r in rows]
    gpu_summary[stage] = {
        'trial_count': len(rows),
        'median_of_trial_medians_ms': median(medians),
        'min_trial_median_ms': min(medians) if medians else None,
        'max_trial_median_ms': max(medians) if medians else None,
        'trial_rows': rows,
    }

same_case = [t for t in extra if t.get('label') == 'same_case_01_x5']
result = {
    'core_trial_count': len(core),
    'extra_trial_count': len(extra),
    'crashed_trial_count': sum(t.get('status') == 'crashed' for t in trials),
    'all_trials': trials,
    'per_color': color_summary,
    'order_comparison': order_comparison,
    'same_case_01_x5': same_case,
    'gpu_ms_analysis': gpu_summary,
    'decision': 'variance too large, need an engineering change before Stage C',
}
OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False))

lines = ['# Stage B variance tables', '', f"Core trials: {len(core)}; extra controlled trials: {len(extra)}.", '']
lines += ['| Color | n | All centre_pct values | Median | Worst | Threshold | Median pass | Worst >=30 |',
          '|---|---:|---|---:|---:|---:|---|---|']
for color in ('red', 'purple', 'blue'):
    s = color_summary[color]
    lines.append(f"| {color} | {s['count']} | {s['all_centre_pct']} | {s['median_centre_pct']} | {s['worst_centre_pct']} | {s['median_threshold_pct']} | {s['median_pass']} | {s['worst_pass']} |")
lines += ['', '## Per-run values', '']
for run in sorted(by_run):
    lines.append(f"- `{run}`: {[t.get('centre_pct') for t in by_run[run]]}")
lines += ['', '## Order comparison', '']
for run, row in order_comparison.items():
    lines.append(f"- `{run}` canonical={row['canonical_centre_pct']}; shuffled={row['shuffled_centre_pct']}; delta={row['shuffled_minus_canonical']}")
lines += ['', '## GPU timing', '']
for stage, row in gpu_summary.items():
    lines.append(f"- `{stage}`: trial median range {row['min_trial_median_ms']}-{row['max_trial_median_ms']} ms; aggregate median {row['median_of_trial_medians_ms']} ms.")
OUT_MD.write_text('\n'.join(lines) + '\n')
print(json.dumps({'core_trial_count': len(core), 'extra_trial_count': len(extra),
                  'per_color': color_summary, 'gpu_ms_analysis': gpu_summary}, indent=2))
