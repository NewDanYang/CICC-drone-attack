import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'task3_1_tools'
OUT.mkdir(exist_ok=True)
rows = [json.loads(s) for s in (ROOT / 'final_eval_gated_20261018T233118/predictions.jsonl').read_text().splitlines()]
labels = []
for row in rows:
    group = row['truth']
    name = Path(row['image']).name
    n = int(Path(name).stem.split('_')[1])
    visible = ['red']
    if group == 'red':
        status = 'visible'
        note = 'Red visible; brick wall partially occludes early frames.'
    elif group == 'purple':
        visible.append('purple')
        status = 'visible'
        note = 'Purple visible; right image edge truncates frames 000-004.' if n <= 4 else 'Purple visible at right.'
    elif n <= 13:
        visible.append('blue')
        status = 'visible'
        note = 'Small blue balloon partly occluded by sign crossbar; wall also occludes late frames.'
    elif n == 14:
        status = 'uncertain'
        note = 'Only a tiny blue sliver at brick-wall edge; color pixels remain but balloon identity is not independently clear.'
    else:
        status = 'not_visible'
        note = 'Blue balloon hidden by brick wall; no independently identifiable balloon pixels.'
    p = ROOT / 'eval_frames_gated' / group / name
    labels.append({
        'image': f'{group}/{name}', 'collection_group': group,
        'target_visibility': status, 'visible_colors': sorted(visible),
        'uncertain_colors': ['blue'] if status == 'uncertain' else [],
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
        'review_method': 'assistant visual review of original 640x480 frames and enlarged inspection crops',
        'review_status': 'provisional_second_review_recommended',
        'note': note,
    })
(OUT / 'labels.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in labels), encoding='utf-8')

invalid = []
for row in rows:
    obj = json.loads(row['raw'])
    if any(a.get('color') not in ('red','blue','purple','unknown') or a.get('region') not in ('left','center','right') for a in obj['balloons']):
        invalid.append(f"{row['truth']}/{Path(row['image']).name}")
(OUT / 'baseline_audit.json').write_text(json.dumps({
    'frames': len(rows), 'schema_invalid_count': len(invalid), 'schema_invalid_frames': invalid,
    'original_group_target_hits': {'red':'20/20','blue':'7/20','purple':'17/20'},
    'visible_target_hits_provisional': {'red':'20/20','blue':'7/14','purple':'17/20'},
    'blue_uncertain': ['blue/frame_014.png'],
    'blue_not_visible': [f'blue/frame_{n:03d}.png' for n in range(15,20)],
    'caution': 'Visible-only metrics are diagnostic, not a new independent acceptance result. Review saw predictions; labels need second review. No region accuracy established.'
}, indent=2), encoding='utf-8')
print('Wrote 60 provisional labels; schema-invalid responses:', len(invalid))
