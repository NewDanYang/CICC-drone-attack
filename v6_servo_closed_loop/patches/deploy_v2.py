"""MD5-guarded activation/rollback. Run build_v2.sh after each activation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

WS=Path('/home/ubuntu/catkin_ws')
MISSION=Path('/home/ubuntu/model/mission_once.py')
BT=WS/'src/mission_pkg/src/bt_ros.cpp'
HEADER=WS/'src/mission_pkg/include/nodes/perception/multimodal_target_tracker.h'
CPP=WS/'src/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp'
PLUGIN=WS/'devel/lib/multimodal_target_tracker.so'
MODULE=Path('/home/ubuntu/model/fm9g_perception')
GUARDS={
    str(WS/'src/mission_pkg/launch/llm_mission.launch'):'5550c580a4822e773a331bcef11f0c47',
    str(WS/'src/mission_pkg/include/base/drone_action_node.h'):'c415ddd8243afcc64c181be45bdac5e3',
    str(WS/'src/mission_pkg/src/nodes/action/visual_servo.cpp'):'a63b57fa127a23cd8bb8e647f078ff21',
    str(WS/'src/mission_pkg/include/nodes/action/visual_servo.h'):'d3324b0458b2160102f9bbf44546d035',
}


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def check(path,allowed):
    if md5(path) not in allowed:
        raise RuntimeError('MD5 mismatch: '+str(path))


def require_idle():
    if Path('/tmp/tcei_formal_trial.lock').exists():
        raise RuntimeError('Formal trial lock exists')
    for name in ('bt_ros',):
        result=subprocess.run(['pgrep','-x',name],capture_output=True,text=True)
        if result.returncode==0:
            raise RuntimeError('Stop idle '+name+' before activating source')
    # Use argv parsing, not pkill -f (which can match its own command).
    # PyTorch may rename comm to pt_main_thread. Read NUL-separated argv so
    # wrapper shells and this checker cannot be mistaken for the Python child.
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal(): continue
        try:
            argv=(process/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,ProcessLookupError,PermissionError):
            continue
        if (argv and re.fullmatch(rb'python(?:[0-9.]*)?',argv[0].rsplit(b'/',1)[-1])
                and any(arg.rsplit(b'/',1)[-1]==b'mission_once.py' for arg in argv[1:])):
            raise RuntimeError('mission_once is still active')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['prepare','candidate','baseline','status'])
    parser.add_argument('backup',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    for path,expected in GUARDS.items(): check(path,{expected})
    manifest=json.loads((root/'v2/manifest.json').read_text(encoding='utf-8'))
    for relative,expected in manifest['package_md5'].items(): check(root/relative,{expected})
    spec=importlib.util.spec_from_file_location('source_patch',root/'patches/patch_v2_sources.py')
    patch=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    if args.mode=='prepare':
        require_idle()
        if args.backup.exists() or MODULE.exists() or HEADER.exists() or CPP.exists() or PLUGIN.exists():
            raise RuntimeError('Backup or candidate paths already exist')
        check(MISSION,{'fca24bf1142ca8cddfb9e8d39c387a43'})
        check(BT,{'9b1cefe9dfa431418435f7f8f63a60ed'})
        args.backup.mkdir(parents=True)
        for src,name in [(MISSION,'mission_once.py'),(BT,'bt_ros.cpp'),
                         (WS/'devel/lib/mission_pkg/bt_ros','bt_ros.binary')]:
            shutil.copy2(src,args.backup/name)
        (args.backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print('PREPARED',args.backup)
        return
    check(args.backup/'mission_once.py',{'fca24bf1142ca8cddfb9e8d39c387a43'})
    check(args.backup/'bt_ros.cpp',{'9b1cefe9dfa431418435f7f8f63a60ed'})
    candidate_mission=patch.patch_entry((args.backup/'mission_once.py').read_bytes(),
                                       (root/'v2/entry_main.py.txt').read_bytes())
    candidate_bt=patch.patch_bt((args.backup/'bt_ros.cpp').read_bytes())
    for path,original,content in [(MISSION,'fca24bf1142ca8cddfb9e8d39c387a43',candidate_mission),
                                  (BT,'9b1cefe9dfa431418435f7f8f63a60ed',candidate_bt)]:
        check(path,{original,hashlib.md5(content).hexdigest()})
    if args.mode=='status':
        is_candidate=md5(MISSION)==hashlib.md5(candidate_mission).hexdigest()
        expected_bt=hashlib.md5(candidate_bt).hexdigest() if is_candidate else '9b1cefe9dfa431418435f7f8f63a60ed'
        check(BT,{expected_bt})
        source_md5={}
        for destination,relative in [(HEADER,'v2/multimodal_target_tracker.h'),(CPP,'v2/multimodal_target_tracker.cpp')]+[
                (MODULE/name,'v2/'+name) for name in ('localizer.py','tracking.py','runtime.py','refinement.py','geometry.py','presence.py','v5_guard.py','v6_estimator.py')]:
            if is_candidate:
                check(destination,{manifest['package_md5'][relative]})
                source_md5[str(destination)]=md5(destination)
            elif destination.exists():
                raise RuntimeError('Rollback left candidate source: '+str(destination))
        if PLUGIN.exists()!=is_candidate: raise RuntimeError('Plugin presence does not match source mode')
        print(json.dumps({'mode':'candidate' if is_candidate else 'baseline',
                          'mission_md5':md5(MISSION),'bt_md5':md5(BT),'source_md5':source_md5,
                          'plugin_md5':md5(PLUGIN) if PLUGIN.exists() else None,
                          'binary_md5':md5(WS/'devel/lib/mission_pkg/bt_ros'),'guards':GUARDS},indent=2))
        return
    require_idle()
    for destination,relative in [(HEADER,'v2/multimodal_target_tracker.h'),(CPP,'v2/multimodal_target_tracker.cpp')]:
        if destination.exists(): check(destination,{manifest['package_md5'][relative]})
    if MODULE.exists():
        for name in ('localizer.py','tracking.py','runtime.py','refinement.py','geometry.py','presence.py','v5_guard.py','v6_estimator.py'):
            check(MODULE/name,{manifest['package_md5']['v2/'+name]})
    archive=args.backup/('activation_'+str(time.time_ns()))
    archive.mkdir()
    if PLUGIN.exists(): shutil.move(str(PLUGIN),str(archive/PLUGIN.name))
    if args.mode=='baseline':
        for path in (HEADER,CPP,MODULE):
            if path.exists(): shutil.move(str(path),str(archive/path.name))
        shutil.copy2(args.backup/'mission_once.py',MISSION)
        shutil.copy2(args.backup/'bt_ros.cpp',BT)
    else:
        MODULE.mkdir(exist_ok=True)
        for name in ('localizer.py','tracking.py','runtime.py','refinement.py','geometry.py','presence.py','v5_guard.py','v6_estimator.py'):
            shutil.copy2(root/'v2'/name,MODULE/name)
        for destination,relative in [(HEADER,'v2/multimodal_target_tracker.h'),(CPP,'v2/multimodal_target_tracker.cpp')]:
            shutil.copy2(root/relative,destination)
            destination.touch()
        MISSION.write_bytes(candidate_mission)
        BT.write_bytes(candidate_bt)
    BT.touch() # Restored historical mtime MUST NOT allow a stale bt_ros binary.
    print('SOURCE_ACTIVATED',args.mode,'BUILD_REQUIRED')
    print('mission_md5',md5(MISSION),'bt_md5',md5(BT))


if __name__=='__main__':
    main()
