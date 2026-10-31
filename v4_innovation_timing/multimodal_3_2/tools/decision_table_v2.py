"""Compact, read-only model-to-tracker diagnostics."""
import argparse
import json
from pathlib import Path
from collections import Counter

parser=argparse.ArgumentParser()
parser.add_argument('session',type=Path)
args=parser.parse_args()
for path in sorted((args.session/'model').glob('*/audit.jsonl')):
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    sources={r['decision']:r for r in rows if r['kind']=='model_source'}
    print('log',path)
    for row in rows:
        if row['kind']=='ready' or row['kind']=='replay' or row['kind']=='inference_error':
            print(json.dumps(row,ensure_ascii=False))
        if row['kind']=='decision' and (row['bbox'] is not None or row.get('model_box') is not None):
            print('valid_decision',json.dumps(row,ensure_ascii=False))
            print('source',json.dumps(sources[row['decision']],ensure_ascii=False))
    print('invalid_publish_reasons',dict(Counter(r.get('reason') for r in rows if r['kind']=='publish')))
    print('last',json.dumps(rows[-1],ensure_ascii=False))
