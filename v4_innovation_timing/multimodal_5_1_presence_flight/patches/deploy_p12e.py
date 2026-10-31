"""MD5-guarded P12e activation and rollback for the stage-B package."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

WS = Path('/home/ubuntu/catkin_ws')
MISSION = Path('/home/ubuntu/model/mission_once.py')
BT = WS/'src/mission_pkg/src/bt_ros.cpp'
HEADER = WS/'src/mission_pkg/include/nodes/perception/multimodal_target_tracker.h'
CPP = WS/'src/mission_pkg/src/nodes/perception/multimodal_target_tracker.cpp'
PLUGIN = WS/'devel/lib/multimodal_target_tracker.so'
MODULE = Path('/home/ubuntu/model/fm9g_perception')
PACKAGE_FILES = ('localizer.py','tracking.py','runtime.py','refinement.py','geometry.py','presence.py')
GUARDS = {
    str(WS/'src/mission_pkg/launch/llm_mission.launch'):'5550c580a4822e773a331bcef11f0c47',
    str(WS/'src/mission_pkg/include/base/drone_action_node.h'):'c415ddd8243afcc64c181be45bdac5e3',
    str(WS/'src/mission_pkg/src/nodes/action/visual_servo.cpp'):'a63b57fa127a23cd8bb8e647f078ff21',
    str(WS/'src/mission_pkg/include/nodes/action/visual_servo.h'):'d3324b0458b2160102f9bbf44546d035',
}


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def check(path, allowed):
    if md5(path) not in allowed:
        raise RuntimeError('MD5 mismatch: '+str(path))


def require_idle():
    if Path('/tmp/tcei_formal_trial.lock').exists():
        raise RuntimeError('Formal trial lock exists')
    if subprocess.run(['pgrep','-x','bt_ros'],capture_output=True).returncode == 0:
        raise RuntimeError('Stop idle bt_ros before activating source')
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            argv=(process/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,ProcessLookupError,PermissionError):
            continue
        if (argv and re.fullmatch(rb'python(?:[0-9.]*)?',argv[0].rsplit(b'/',1)[-1])
                and any(arg.rsplit(b'/',1)[-1]==b'mission_once.py' for arg in argv[1:])):
            raise RuntimeError('mission_once is still active')


def load_package(root):
    manifest=json.loads((root/'v2/manifest.json').read_text(encoding='utf-8'))
    for relative, expected in manifest['package_md5'].items():
        check(root/relative,{expected})
    return manifest


def patch_functions(root):
    spec=importlib.util.spec_from_file_location('source_patch',root/'patches/patch_v2_sources.py')
    patch=importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)
    return patch


def candidate_bytes(root, backup):
    patch=patch_functions(root)
    mission=patch.patch_entry((backup/'mission_once.py').read_bytes(),
                              (root/'v2/entry_main.py.txt').read_bytes())
    bt=patch.patch_bt((backup/'bt_ros.cpp').read_bytes())
    return mission, bt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['prepare','candidate','baseline','status'])
    parser.add_argument('backup',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    manifest=load_package(root)
    for path,expected in GUARDS.items(): check(path,{expected})
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
        state={'mission_md5':md5(MISSION),'bt_md5':md5(BT),
               'binary_md5':md5(WS/'devel/lib/mission_pkg/bt_ros'),
               'guards':GUARDS,'package_md5':manifest['package_md5']}
        (args.backup/'initial_md5.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
        print('PREPARED',args.backup)
        return
    check(args.backup/'mission_once.py',{'fca24bf1142ca8cddfb9e8d39c387a43'})
    check(args.backup/'bt_ros.cpp',{'9b1cefe9dfa431418435f7f8f63a60ed'})
    candidate_mission,candidate_bt=candidate_bytes(root,args.backup)
    candidate_mission_md5=hashlib.md5(candidate_mission).hexdigest()
    candidate_bt_md5=hashlib.md5(candidate_bt).hexdigest()
    check(MISSION,{'fca24bf1142ca8cddfb9e8d39c387a43',candidate_mission_md5})
    check(BT,{'9b1cefe9dfa431418435f7f8f63a60ed',candidate_bt_md5})
    if args.mode=='status':
        candidate=(md5(MISSION)==candidate_mission_md5)
        source_md5={}
        for name in PACKAGE_FILES:
            path=MODULE/name
            if candidate:
                check(path,{manifest['package_md5']['v2/'+name]})
                source_md5[str(path)]=md5(path)
            elif path.exists():
                raise RuntimeError('Rollback left candidate source: '+str(path))
        for path,relative in [(HEADER,'v2/multimodal_target_tracker.h'),(CPP,'v2/multimodal_target_tracker.cpp')]:
            if candidate: check(path,{manifest['package_md5'][relative]})
            elif path.exists(): raise RuntimeError('Rollback left candidate source: '+str(path))
        if PLUGIN.exists()!=candidate: raise RuntimeError('Plugin presence does not match source mode')
        print(json.dumps({'mode':'candidate' if candidate else 'baseline',
                          'mission_md5':md5(MISSION),'bt_md5':md5(BT),
                          'source_md5':source_md5,
                          'plugin_md5':md5(PLUGIN) if PLUGIN.exists() else None,
                          'binary_md5':md5(WS/'devel/lib/mission_pkg/bt_ros'),
                          'guards':GUARDS},indent=2))
        return
    require_idle()
    archive=args.backup/('activation_'+str(time.time_ns())); archive.mkdir()
    if PLUGIN.exists(): shutil.move(str(PLUGIN),str(archive/PLUGIN.name))
    if MODULE.exists(): shutil.move(str(MODULE),str(archive/MODULE.name))
    for path in (HEADER,CPP):
        if path.exists(): shutil.move(str(path),str(archive/path.name))
    if args.mode=='baseline':
        shutil.copy2(args.backup/'mission_once.py',MISSION)
        shutil.copy2(args.backup/'bt_ros.cpp',BT)
    else:
        MODULE.mkdir(parents=True,exist_ok=True)
        for name in PACKAGE_FILES: shutil.copy2(root/'v2'/name,MODULE/name)
        shutil.copy2(root/'v2/multimodal_target_tracker.h',HEADER)
        shutil.copy2(root/'v2/multimodal_target_tracker.cpp',CPP)
        MISSION.write_bytes(candidate_mission)
        BT.write_bytes(candidate_bt)
    BT.touch()
    print('SOURCE_ACTIVATED',args.mode,'BUILD_REQUIRED')
    print('mission_md5',md5(MISSION),'bt_md5',md5(BT))


if __name__=='__main__': main()
