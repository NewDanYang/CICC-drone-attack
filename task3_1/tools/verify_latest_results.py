"""Recompute saved evaluation metrics without loading FM9G or importing torch."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'latest_results_review'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p / 100
    a, b = math.floor(k), math.ceil(k)
    return values[a] + (values[b] - values[a]) * (k - a)


def decode(raw):
    text = raw.strip()
    parts = text.splitlines()
    if len(parts) >= 3 and parts[0].lower() in ('```json', '```') and parts[-1] == '```':
        text = '\n'.join(parts[1:-1])
    obj = json.loads(text)
    assert isinstance(obj, dict) and set(obj) == {'balloons'}
    assert isinstance(obj['balloons'], list)
    for item in obj['balloons']:
        assert isinstance(item, dict) and set(item) == {'color', 'region'}
        assert item['color'] in ('red', 'blue', 'purple', 'unknown')
        assert item['region'] in ('left', 'center', 'right')
    return sorted({x['color'] for x in obj['balloons'] if x['color'] != 'unknown'}), sum(x['color'] == 'unknown' for x in obj['balloons'])


def main():
    runs = sorted(p for p in BASE.iterdir() if (p / 'summary.json').is_file())
    checked = []
    prompts = []
    all_hashes = []
    for run in runs:
        rows, labels = lines(run / 'predictions.jsonl'), lines(run / 'labels.jsonl')
        summary, config = load(run / 'summary.json'), load(run / 'config.json')
        prompts.append(config['prompt'])
        assert len(rows) == len(labels) == summary['frames']
        assert len({x['image'] for x in rows}) == len(rows)
        is_shift = run.name.startswith('blue_shift')
        data = BASE / 'blue_shift_diagnostic_20261019T180126_042698Z' if is_shift else ROOT / 'eval_frames_gated'
        recomputed = []
        for row, label in zip(rows, labels):
            assert all(row[k] == v for k, v in label.items())
            assert hashlib.sha256((data / row['image']).read_bytes()).hexdigest() == row['sha256']
            all_hashes.append(row['sha256'])
            colors, unknown, valid = [], 0, False
            if not row['inference_error']:
                try:
                    colors, unknown = decode(row['raw'])
                    valid = True
                except (ValueError, AssertionError, TypeError, KeyError):
                    pass
            assert valid == row['schema_valid']
            assert colors == row['predicted_colors']
            assert unknown == row['unknown_count']
            hit = valid and row['collection_group'] in colors
            if row['target_visibility'] != 'visible':
                hit = None
            exact = valid and colors == row['visible_colors'] and unknown == 0
            if row['target_visibility'] == 'uncertain':
                exact = None
            assert hit == row['target_hit'] and exact == row['color_set_exact']
            recomputed.append(dict(row, target_hit=hit, color_set_exact=exact))
        certain = [x for x in recomputed if x['target_visibility'] != 'uncertain']
        assert len(certain) == summary['color_set_exact_frames']
        assert sum(x['color_set_exact'] is True for x in certain) == summary['color_set_exact_correct']
        assert sum(x['color_set_exact'] is True for x in certain) / len(certain) == summary['color_set_exact_accuracy']
        assert sum(not x['schema_valid'] and not x['inference_error'] for x in rows) == summary['schema_invalid']
        assert sum(bool(x['inference_error']) for x in rows) == summary['inference_errors']
        assert sum(x['unknown_count'] > 0 for x in rows) == summary['unknown_response_count']
        for key, group in summary['per_collection_group'].items():
            part = [x for x in rows if x['collection_group'] == key]
            positive = [x for x in part if x['target_visibility'] == 'visible']
            negative = [x for x in part if x['target_visibility'] == 'not_visible']
            hits = sum(x['target_hit'] is True for x in positive)
            assert len(part) == group['frames']
            assert len(positive) == group['visible_target_frames']
            assert hits == group['visible_target_hits']
            assert hits / len(positive) == group['visible_target_hit_rate']
            assert len(negative) == group['not_visible_frames']
            assert sum(x['target_visibility'] == 'uncertain' for x in part) == group['uncertain_target_frames']
            assert sum(x['schema_valid'] and key in x['predicted_colors'] for x in negative) == group['false_target_predictions_on_not_visible']
            for p in (50, 95):
                actual = percentile([x['latency_s'] for x in part if not x['inference_error']], p)
                assert math.isclose(actual, group[f'successful_call_p{p}_s'], abs_tol=1e-10)
        for p in (50, 95):
            assert math.isclose(percentile([x['latency_s'] for x in rows if not x['inference_error']], p), summary[f'successful_call_p{p}_s'], abs_tol=1e-10)
        if is_shift:
            assert hashlib.sha256((run / 'evaluator.py').read_bytes()).hexdigest() == config['evaluator_sha256']
            assert hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest() == config['labels_sha256']
            capture = load(data / 'capture.json')
            manifest = lines(data / 'manifest.jsonl')
            assert capture['saved_frames'] == len(manifest) == len(rows)
            assert len({tuple(x['header']) for x in manifest}) == len(rows)
            assert {x['image']: x['sha256'] for x in manifest} == {x['image']: x['sha256'] for x in rows}
        else:
            assert hashlib.sha256((run / 'labels.jsonl').read_bytes()).hexdigest() == config['labels_sha256']
        checked.append({'run': run.name, 'rows': len(rows), 'image_hashes': 'PASS', 'raw_parse_and_row_scores': 'PASS', 'summary_metrics_and_percentiles': 'PASS'})
    assert len(runs) == 2 and prompts[0] == prompts[1]
    result = {'status': 'PASS', 'runs': checked, 'same_prompt': True, 'unique_image_hashes': len(set(all_hashes)), 'total_image_records': len(all_hashes), 'annotation_status': 'Provisional visual labels; metrics verification does not independently validate labels.'}
    (ROOT / 'verification_latest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
