"""Verify every included member against its original-file SHA256 manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

p=argparse.ArgumentParser();p.add_argument('directory',type=Path);args=p.parse_args()
reports=[]
for path in sorted(args.directory.glob('*.tar.gz')):
    with tarfile.open(path) as archive:
        manifest=json.load(archive.extractfile('MANIFEST.json'))
        expected={'MANIFEST.json'};checked=0;retained=0
        for item in manifest['files']:
            if not item['included']:retained+=1;continue
            name=item['scope']+'/'+item['path'];expected.add(name)
            member=archive.getmember(name)
            assert member.isfile() and member.size==item['bytes'],name
            content=archive.extractfile(member).read()
            assert hashlib.sha256(content).hexdigest()==item['sha256'],name
            checked+=1
        assert set(archive.getnames())==expected,path.name
        reports.append(dict(archive=path.name,checked_files=checked,server_only_files=retained,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
print(json.dumps(reports,indent=2))
