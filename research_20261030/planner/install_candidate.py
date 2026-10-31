"""Generate/install a reversible Ego candidate in an ISOLATED workspace only.

Never modifies launch speed limits. Disabled until manager/certified_shortcut is true.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

def replace_once(data,old,new,count=1):
    newline=b'\r\n' if b'\r\n' in data else b'\n'
    old=old.replace('\n',newline.decode()).encode()
    new=new.replace('\n',newline.decode()).encode()
    if data.count(old)!=count: raise ValueError('Unrecognized source layout: '+repr(old))
    return data.replace(old,new)

def prepare(root):
    files={}
    path=root/'include/plan_manage/planner_manager.h';data=path.read_bytes()
    files[path]=replace_once(data,'    int continous_failures_count_{0};',
        '    int continous_failures_count_{0};\n'
        '    bool certified_shortcut_{false};\n'
        '    bool certified_cruise_{true};\n'
        '    bool certified_quintic_{true};\n'
        '    bool certified_hermite_{true};\n'
        '    bool certified_spatial_{true};')
    path=root/'src/planner_manager.cpp';data=path.read_bytes()
    data=replace_once(data,'#include <thread>', '#include <thread>\n#include <plan_manage/ego_adapter.hpp>')
    data=replace_once(data,'    local_data_.traj_id_ = 0;',
        '    nh.param("manager/certified_shortcut", certified_shortcut_, false);\n'
        '    nh.param("manager/certified_cruise", certified_cruise_, true);\n'
        '    nh.param("manager/certified_quintic", certified_quintic_, true);\n'
        '    nh.param("manager/certified_hermite", certified_hermite_, true);\n'
        '    nh.param("manager/certified_spatial", certified_spatial_, true);\n'
        '    local_data_.traj_id_ = 0;')
    data=replace_once(data,'    // save planned results\n    updateTrajInfo(pos, ros::Time::now());',
        '    // Candidate changes the manager trajectory BEFORE publishing and future replans.\n'
        '    if (certified_shortcut_)\n'
        '      cicc::improve(pos, grid_map_, {pp_.max_vel_, pp_.max_acc_, pp_.max_jerk_},\n'
        '                    certified_cruise_, certified_quintic_, certified_hermite_, certified_spatial_);\n'
        '    // save planned results\n    updateTrajInfo(pos, ros::Time::now());')
    files[path]=data
    path=root/'src/ego_replan_fsm.cpp';data=path.read_bytes()
    files[path]=replace_once(data,'bspline.order = 3;',
        'bspline.order = info->position_traj_.getKnot().size() -\n'
        '                      info->position_traj_.getControlPoint().cols() - 1;',2)
    for name in ('certified_shortcut.hpp','ego_adapter.hpp'):
        path=root/'include/plan_manage'/name
        if path.exists():raise ValueError('Candidate already installed: '+str(path))
        files[path]=Path(__file__).with_name(name).read_bytes()
    return files

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('plan_manage',type=Path)
    ap.add_argument('--apply',action='store_true')
    ap.add_argument('--rollback',action='store_true')
    args=ap.parse_args();root=args.plan_manage.resolve()
    if args.apply and ('official_baseline' in root.parts or
        any(Path(p)==root or Path(p) in root.parents for p in ('/home/ubuntu/catkin_ws','/home/ubuntu/cicc_v1_stage_20261005'))):
        raise ValueError('Refusing protected baseline/formal workspace; create an isolated workspace first')
    manifest=root/'certified_shortcut_manifest.json'
    if args.rollback:
        records=json.loads(manifest.read_text())
        for row in records:
            p=root/row['path']
            if hashlib.sha256(p.read_bytes()).hexdigest()!=row['after']:raise ValueError('Edited after install: '+str(p))
            if row['before'] is not None:
                backup=root/row['backup']
                if hashlib.sha256(backup.read_bytes()).hexdigest()!=row['before']:raise ValueError('Backup hash mismatch')
        for row in records:
            p=root/row['path']
            if row['before'] is None:p.unlink()
            else:shutil.copyfile(root/row['backup'],p)
        manifest.rename(manifest.with_suffix('.rolled_back.json'))
        print('Rollback source hashes verified; rebuild candidate workspace before running.');return
    files=prepare(root);records=[]
    if manifest.exists():raise ValueError('Manifest exists')
    for p,data in files.items():
        before=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        backup=p.with_name(p.name+'.pre_certified_shortcut')
        if backup.exists():raise ValueError('Backup exists: '+str(backup))
        records.append({'path':str(p.relative_to(root)), 'before':before,
                        'after':hashlib.sha256(data).hexdigest(), 'backup':str(backup.relative_to(root))})
    if args.apply:
        for p,data in files.items():
            if p.exists():shutil.copyfile(p,p.with_name(p.name+'.pre_certified_shortcut'))
            p.write_bytes(data)
        manifest.write_text(json.dumps(records,indent=2))
    print(json.dumps({'applied':args.apply,'files':records},indent=2))

if __name__=='__main__':main()
