"""Freeze the 24-frame paired red diagnostic set before model calls."""
import argparse,hashlib,json,shutil,tarfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('diagnosis',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
notes=json.loads((args.diagnosis/'manual_annotations.json').read_text(encoding='utf-8'))['rows']
red=[r for r in notes if r['color']=='red'];chosen=[r for r in red if r['visibility']!='not_visible']
for trial in sorted({r['trial'] for r in red}):
    part=[r for r in red if r['trial']==trial and r['visibility']=='not_visible']
    chosen.extend(part[round((len(part)-1)*q/4)] for q in range(5))
assert len(chosen)==len({r['decision'] for r in chosen})==24
chosen.sort(key=lambda r:r['review_number'])
args.output.mkdir(parents=True,exist_ok=True);(args.output/'images').mkdir(exist_ok=True)
for row in chosen:
    source=args.diagnosis/'red_all'/(row['decision']+'.png')
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['source_sha256']
    shutil.copyfile(source,args.output/'images'/source.name)
    row['image']='images/'+source.name
(args.output/'cases.json').write_text(json.dumps(chosen,indent=2)+'\n',encoding='utf-8')
with tarfile.open(args.output.with_suffix('.tar.gz'),'w:gz') as archive:
    for path in sorted(args.output.rglob('*')):
        if path.is_file():archive.add(path,arcname=path.relative_to(args.output).as_posix())
print('frames',len(chosen),'cases_sha256',hashlib.sha256((args.output/'cases.json').read_bytes()).hexdigest())
