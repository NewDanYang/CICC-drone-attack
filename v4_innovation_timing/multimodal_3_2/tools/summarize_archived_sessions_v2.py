"""Recompute demo/development statistics from archives plus selected native CSV.

Extract only JSONL and actual X11 screenshots to a temporary directory. Native
paths inside archived receipts are historical and need not exist locally.
"""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import re
import tarfile
import tempfile


def main():
    p=argparse.ArgumentParser()
    p.add_argument('archives',type=Path)
    p.add_argument('--native-csv',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    spec=importlib.util.spec_from_file_location('summary',Path(__file__).with_name('summarize_session_v2.py'))
    summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)
    with args.native_csv.open(encoding='utf-8',newline='') as stream:
        native={r['run_id']:r for r in csv.DictReader(stream)}
    results=[];selected=[]
    for archive_path in sorted(args.archives.glob('*.tar.gz')):
        with tarfile.open(archive_path,'r:gz') as archive,tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for member in archive.getmembers():
                if member.name.startswith('session/') and (member.name.endswith('.jsonl') or
                        member.name.startswith('session/audit/screenshots/') and member.name.endswith('.png')):
                    target=(root/member.name).resolve()
                    if root.resolve() not in target.parents:raise ValueError('Unsafe archive path')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as stream:target.write_bytes(stream.read())
            data=summary.summarize(root/'session')
            data['session']=json.load(archive.extractfile('MANIFEST.json'))['server_session']
            observer=archive.extractfile('native/observer.out').read().decode('utf-8')
            match=re.search(r'^run_id=(.+)$',observer,re.M)
            row=native[match[1].strip()] if match else None
            if row:selected.append(row)
            data.update(archive=archive_path.name,native_row=row)
            results.append(data)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with args.output.with_suffix('.csv').open('w',encoding='utf-8',newline='') as stream:
        if selected:
            writer=csv.DictWriter(stream,fieldnames=list(selected[0]));writer.writeheader();writer.writerows(selected)
    for r in results:
        print(r['archive'],r['processor_items'],r['consumed_logs'],r['actual_window_screenshots'],
              (r['native_row'] or {}).get('total_time'))


if __name__=='__main__':main()
