#!/usr/bin/env python3
"""Offline, audited speed-only restoration. Default is a read-only plan."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
BT = Path('src/mission_pkg/src/bt_ros.cpp')
EGO = Path('src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch')
LAUNCH = Path('src/mission_pkg/launch/llm_mission.launch')
VISUAL = Path('src/mission_pkg/src/nodes/action/visual_servo.cpp')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalize(data, kind):
    if b'\r\n' in data and data.count(b'\r\n') != data.count(b'\n'):
        raise ValueError('mixed line endings')
    nl = '\r\n' if b'\r\n' in data else '\n'
    text = data.decode('utf-8').replace('\r\n', '\n')
    if kind == 'bt':
        for var, param, value in [('vs_fwd_vel','forward_velocity','1.0'),
                                  ('vs_sprint_v','sprint_velocity','1.5'),
                                  ('vs_sprint_t','sprint_time','1.2')]:
            pattern = r'(?m)^(?P<indent>[ \t]*)std::string\s+' + var + r'\s*=\s*std::to_string\((?P<expr>[^;]+)\);'
            matches = list(re.finditer(pattern, text))
            if len(matches) != 1:
                raise ValueError('missing/non-unique '+var+' declaration')
            m = matches[0]
            # Accept exactly the reviewed generic and color-specific expressions.
            expr = re.sub(r'\s+', '', m['expr'])
            generic = f'getDbl("visual_servo/{param}",{value})'
            allowed = {generic}
            if var == 'vs_sprint_v':
                blue = 'color=="blue"?getDbl("visual_servo/blue_sprint_velocity",1.0):'
                purple = 'color=="purple"?getDbl("visual_servo/purple_sprint_velocity",0.6):'
                allowed |= {blue+generic, blue+purple+generic, purple+generic}
            elif var == 'vs_fwd_vel':
                allowed.add('color=="purple"?getDbl("visual_servo/purple_forward_velocity",0.6):'+generic)
            else:
                allowed.add('color=="purple"?getDbl("visual_servo/purple_sprint_time",0.5):'+generic)
            if expr not in allowed:
                raise ValueError('unreviewed '+var+' expression')
            # Preserve an already official declaration byte-for-byte.
            if expr != generic:
                replacement = m['indent'] + f'std::string {var} = std::to_string(getDbl("visual_servo/{param}", {value}));'
                text = text[:m.start()] + replacement + text[m.end():]
    elif kind == 'ego':
        pattern = r'(<arg\s+name="max_vel"\s+value=")(0\.(?:3|30|35|4|40|45|5|50))("\s*/>)'
        if len(re.findall(pattern, text)) != 1:
            raise ValueError('missing/non-unique or unreviewed FS-J310 max_vel')
        text = re.sub(pattern, lambda m: m[1]+'0.3'+m[3], text)
    elif kind == 'launch':
        for param, value in [('forward_velocity','1.0'),('sprint_velocity','1.5'),('sprint_time','1.2')]:
            pattern = r'(<param\s+name="visual_servo/'+param+r'"\s+value=")([0-9.]+)(")'
            matches = list(re.finditer(pattern,text))
            allowed = {'forward_velocity':{0.35,0.6,1.0},'sprint_velocity':{0.6,0.8,1.0,1.5},'sprint_time':{0.4,0.5,1.2}}
            if len(matches)!=1 or float(matches[0][2]) not in allowed[param]:
                raise ValueError('unreviewed/non-unique formal launch '+param)
            m=matches[0]
            if float(m[2])!=float(value):text=text[:m.start(2)]+value+text[m.end(2):]
    elif kind == 'visual':
        defaults={'forward_velocity':0.35,'sprint_velocity':1.5,'sprint_time':1.2,
                  'max_yaw_rate':0.5,'max_vz':0.3,'search_yaw_rate':0.3}
        for name,value in defaults.items():
            found=re.findall(r'InputPort<double>\("'+name+r'",\s*([0-9.]+)',text)
            if len(found)!=1 or float(found[0])!=value:
                raise ValueError('unreviewed VisualServo default '+name)
        if 'double yaw_rate = -(k_p_yaw_rate_ * err_after_dz + k_d_yaw_rate_ * d_err);' not in text:
            raise ValueError('unreviewed yaw-rate equation')
        if 'double vx = forward_velocity_ * align_ratio;' not in text:
            raise ValueError('unreviewed approach-velocity equation')
        if 'yaw_probe_enabled_' in text or 'SPRINT_ABORT_NEAR_TARGET' in text:
            raise ValueError('diagnostic yaw probe or shortened sprint found')
    else:
        raise ValueError('unknown target kind')
    return text.replace('\n', nl).encode('utf-8')


def fingerprint(data, kind):
    """Ignore only reviewed speed declarations, numeric spelling and line endings."""
    text = normalize(data, kind).decode('utf-8').replace('\r\n', '\n')
    if kind == 'bt':
        text = re.sub(r'(?m)^[ \t]*std::string\s+(vs_fwd_vel|vs_sprint_v|vs_sprint_t)\s*=.*?;$',
                      lambda m: 'AUDITED_SPEED_DECLARATION:'+m[1], text)
    if kind == 'launch':
        text=re.sub(r'(<param\s+name="visual_servo/(?:forward_velocity|sprint_velocity|sprint_time)"\s+value=")[0-9.]+(")',r'\g<1>AUDITED\2',text)
    return sha(text.encode('utf-8'))


def checked_path(root, rel):
    # Do not follow a symlink/junction into another workspace.
    path = root / rel
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(root):
        raise ValueError('symlink/junction or path escape: '+str(path))
    if not path.is_file():
        raise ValueError('missing required source: '+str(path))
    return path


def restore_backup(folder):
    folder = folder.resolve()
    record = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    plans = []
    for item in record['changes']:
        target = Path(item['target'])
        saved = folder / item['backup']
        if not saved.resolve().is_relative_to(folder) or saved.is_symlink():
            raise ValueError('invalid backup path')
        if target.resolve() != target.absolute():
            raise ValueError('target became a symlink/junction')
        data = saved.read_bytes()
        if sha(data) != item['before_sha256'] or sha(target.read_bytes()) != item['after_sha256']:
            raise ValueError('backup/current hash mismatch; refusing rollback')
        plans.append((target, data))
    for target, data in plans:
        target.write_bytes(data)
    print(json.dumps({'rolled_back':len(plans),'backup':str(folder)}))


def apply_targets(targets, backup=None, apply=False):
    approved = json.loads((HERE/'approved_fingerprints.json').read_text(encoding='utf-8'))
    plans = []
    for path, kind in targets:
        before = path.read_bytes()
        after = normalize(before, kind)
        if fingerprint(before, kind) not in approved[kind]:
            raise ValueError('source has unreviewed non-speed differences: '+str(path))
        if before != after:
            plans.append((path, before, after))
    result = {'mode':'apply' if apply else 'check','changed_files':len(plans),
              'files':[{'target':str(p),'before_sha256':sha(b),'after_sha256':sha(a)} for p,b,a in plans]}
    if not apply or not plans:
        print(json.dumps(result, indent=2)); return result
    if backup is None:
        raise ValueError('--backup is required with --apply')
    backup = backup.absolute()
    if backup.exists() or backup.resolve() != backup:
        raise ValueError('backup must be a new regular directory')
    backup.mkdir(parents=True, exist_ok=False)
    entries=[]
    for i,(path,before,after) in enumerate(plans):
        saved = f'{i:03d}-{path.name}.before'
        (backup/saved).write_bytes(before)
        entries.append({'target':str(path),'backup':saved,'before_sha256':sha(before),'after_sha256':sha(after)})
    record={'changes':entries,'status':'prepared'}
    manifest=backup/'manifest.json'
    manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    written=[]
    try:
        for path,before,after in plans:
            if path.read_bytes()!=before:raise ValueError('source changed after preflight: '+str(path))
            written.append((path,before))
            path.write_bytes(after)
            if path.read_bytes()!=after:raise ValueError('write verification failed')
    except Exception:
        for path,before in reversed(written):path.write_bytes(before)
        record['status']='automatically_rolled_back'
        manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        raise
    record['status']='applied'
    manifest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    result['backup']=str(backup)
    print(json.dumps(result,indent=2)); return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catkin-root',type=Path)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--kind',choices=['bt','ego','launch','visual'])
    parser.add_argument('--only-bt',action='store_true')
    parser.add_argument('--only-ego',action='store_true')
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--rollback',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.rollback:
            if args.apply or args.source or args.catkin_root:raise ValueError('rollback is a separate action')
            return restore_backup(args.rollback)
        if args.source:
            if not args.kind:raise ValueError('--kind is required with --source')
            path=args.source.absolute()
            if path.resolve()!=path or not path.is_file():raise ValueError('invalid source path')
            targets=[(path,args.kind)]
        else:
            if args.catkin_root is None:raise ValueError('--catkin-root is required')
            root=args.catkin_root.absolute()
            if root.resolve()!=root:raise ValueError('catkin root is a symlink/junction')
            if args.only_bt and args.only_ego:raise ValueError('choose at most one target restriction')
            targets=[]
            if not args.only_ego:targets.append((checked_path(root,BT),'bt'))
            if not args.only_ego and not args.only_bt:targets.append((checked_path(root,LAUNCH),'launch'))
            if not args.only_ego and not args.only_bt:targets.append((checked_path(root,VISUAL),'visual'))
            if not args.only_bt:targets.append((checked_path(root,EGO),'ego'))
        return apply_targets(targets,args.backup,args.apply)
    except (ValueError,OSError,UnicodeError,KeyError) as exc:
        raise SystemExit('NO CHANGE / CHECK FAILED: '+str(exc))


if __name__=='__main__':
    main()

