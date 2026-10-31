"""Bundle 155 reviewed raw source PNGs and 96 exact representative tile PNGs."""
import argparse,hashlib,io,json,tarfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('evidence',type=Path);args=p.parse_args()
root=args.evidence;diagnosis=root/'diagnosis'
notes=json.loads((diagnosis/'manual_annotations.json').read_text(encoding='utf-8'))['rows']
selection={r['decision']:r for r in json.loads((diagnosis/'review_selection.json').read_text(encoding='utf-8'))}
files=[]
for row in notes:
    path=(diagnosis/'red_all'/(row['decision']+'.png') if row['color']=='red' else
          diagnosis/'review'/selection[row['decision']]['image'])
    assert hashlib.sha256(path.read_bytes()).hexdigest()==row['source_sha256']
    files.append((path,'sources/'+row['decision']+'.png'))
tiles=json.loads((diagnosis/'tile_examples/tile_manifest.json').read_text(encoding='utf-8'))
for row in tiles:
    path=diagnosis/'tile_examples'/row['file']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==row['file_sha256']
    files.append((path,'tiles/'+row['file']))
assert len(notes)==155 and len(tiles)==96 and len({name for _,name in files})==251
manifest=[];destination=root/'diagnostic_source_frames.tar.gz'
with tarfile.open(destination,'w:gz') as archive:
    for path,name in files:
        content=path.read_bytes();member=tarfile.TarInfo(name);member.size=len(content)
        archive.addfile(member,io.BytesIO(content))
        manifest.append(dict(path=name,bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
    content=(json.dumps(manifest,indent=2)+'\n').encode();member=tarfile.TarInfo('MANIFEST.json');member.size=len(content)
    archive.addfile(member,io.BytesIO(content))
with tarfile.open(destination) as archive:
    for row in manifest:
        content=archive.extractfile(row['path']).read()
        assert len(content)==row['bytes'] and hashlib.sha256(content).hexdigest()==row['sha256']
receipt=dict(archive=destination.name,bytes=destination.stat().st_size,
    sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),source_pngs=155,exact_tile_pngs=96,verified_files=len(manifest))
(root/'diagnostic_source_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt,indent=2))
