"""Freeze exact deployable bytes and create one upload archive."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    files=[root/relative for relative in [
        'v2/localizer.py','v2/tracking.py','v2/runtime.py','v2/refinement.py','v2/geometry.py',
        'v2/multimodal_target_tracker.h','v2/multimodal_target_tracker.cpp',
        'v2/entry_main.py.txt','v2/mission_once.py','v2/bt_ros.cpp',
        'patches/deploy_v2.py','patches/build_v2.sh','patches/patch_v2_sources.py',
        'tools/test_v2_guards.py','tools/run_one_v2.sh','tools/switch_condition_v2.sh',
        'tools/postflight_snapshot_v2.py','tools/observe_trial_v2.py',
        'tools/summarize_session_v2.py','tools/decision_table_v2.py','tools/inspect_stage_v2.py']]
    manifest={'package_md5':{p.relative_to(root).as_posix():hashlib.md5(p.read_bytes()).hexdigest() for p in files}}
    manifest_path=root/'v2/manifest.json'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    with tarfile.open(args.output,'w:gz') as archive:
        for path in files+[manifest_path]:
            archive.add(path,arcname=path.relative_to(root).as_posix())
    print(json.dumps({'archive':str(args.output),'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'files':len(files)+1},indent=2))


if __name__=='__main__': main()
