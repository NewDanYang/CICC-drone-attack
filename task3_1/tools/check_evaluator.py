import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('evaluator', root / 'task3_1_tools/evaluate_3_1_v2.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate('{"balloons":[{"color":"blue","region":"right"}]}')
module.validate('{"balloons":[]}')
module.validate('```json\n{"balloons":[{"color":"blue","region":"right"}]}\n```')
module.validate('```\n{"balloons":[]}\n```')
for value in [
    '{"balloons":[{"color":"blue|purple","region":"right"}]}',
    '{"balloons":[{"color":"blue","region":"middle"}]}',
    '{"balloons":[{"color":"blue"}]}',
    '{"balloons":{},"extra":true}',
    'not JSON',
    'Explanation\n```json\n{"balloons":[]}\n```',
    '```json\n{"balloons":[]}\n```\nExplanation',
    '```json\n{"balloons":[{"color":"blue|purple","region":"right"}]}\n```',
]:
    try:
        module.validate(value)
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError('Invalid response was accepted: ' + value)
assert module.pct([1, 2, 3], 50) == 2
assert abs(module.pct([1, 2, 3], 95) - 2.9) < 1e-9
labels = [json.loads(s) for s in (root / 'task3_1_tools/labels.jsonl').read_text().splitlines()]
old = [json.loads(s) for s in (root / 'final_eval_gated_20261018T233118/predictions.jsonl').read_text().splitlines()]
by_key = {f"{r['truth']}/{Path(r['image']).name}": r for r in old}
rows = []
for label in labels:
    old_row = by_key[label['image']]
    colors = []
    valid = True
    try:
        _, balloons = module.validate(old_row['raw'])
        colors = sorted({b['color'] for b in balloons if b['color'] != 'unknown'})
    except ValueError:
        valid = False
    rows.append(dict(label, predicted_colors=colors, schema_valid=valid,
                     target_hit=valid and label['collection_group'] in colors,
                     color_set_exact=valid and colors == label['visible_colors'],
                     unknown_count=0, inference_error=None, latency_s=old_row['latency_s']))
result = module.score(rows)
assert result['schema_invalid'] == 9
assert result['per_collection_group']['blue']['visible_target_frames'] == 14
assert result['per_collection_group']['blue']['visible_target_hits'] == 7
assert result['color_set_exact_frames'] == 59
print('PASS: enum validation, JSON/schema rejection, percentile and baseline scoring')
