"""Archive audit/native logs, all model inputs/windows, selected raw camera JPEGs.

Every original file is hashed, including camera frames retained on the server.
The archive explicitly distinguishes shipped files from unshipped full RGB frames.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile


def main():
    p=argparse.ArgumentParser()
    p.add_argument('session',type=Path)
    p.add_argument('output',type=Path)
    args=p.parse_args()
    files=[];manifest=[]
    for path in sorted(args.session.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(args.session)
        camera=relative.parts[:2]==('audit','frames')
        # Preserve exact JPEGs at ~1 fps in Git; all ~10 Hz frames stay on server.
        selected=not camera or (path.stem.isdecimal() and int(path.stem)%10==1)
        if path.name=='capture.xwd':selected=False
        manifest.append(dict(scope='session',path=relative.as_posix(),bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),included=selected))
        if selected:files.append((path,'session/'+relative.as_posix()))
    trial_path=args.session/'trial_path.txt'
    if trial_path.exists():
        trial=Path(trial_path.read_text().strip())
    else:
        import re
        matches=re.findall(r'^experiment_dir=(.+)$',(args.session/'formal_runner.out').read_text(),re.M)
        trial=Path(matches[-1]) if matches else None
    if trial:
        for path in sorted(trial.rglob('*')):
            if not path.is_file():continue
            relative=path.relative_to(trial).as_posix()
            files.append((path,'native/'+relative))
            manifest.append(dict(scope='native',path=relative,bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),included=True))
    metadata=dict(server_session=str(args.session),server_trial=str(trial) if trial else None,
        camera_policy='exact JPEG every tenth observer capture included; ALL RGB frames retained at server path with hashes',
        model_policy='ALL model audit JSONL, source PNGs, actual region PNG inputs and windows included',files=manifest)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(args.output,'w:gz',compresslevel=6) as archive:
        raw=json.dumps(metadata,ensure_ascii=False,indent=2).encode()
        entry=tarfile.TarInfo('MANIFEST.json');entry.size=len(raw);archive.addfile(entry,io.BytesIO(raw))
        for path,name in files:archive.add(path,arcname=name)
    print(json.dumps(dict(archive=str(args.output),bytes=args.output.stat().st_size,
        sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),included=len(files),originals=len(manifest)),indent=2))


if __name__=='__main__':main()
