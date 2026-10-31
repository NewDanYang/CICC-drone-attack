"""Read-only Linux probe. No ROS commands, parameter writes, restarts or flight."""
import hashlib
import json
import os
from pathlib import Path
import time

def parse_project_mappings(text):
    """Keep file identity; a replaced on-disk .so is not the mapped old .so."""
    result=[];seen=set()
    for line in text.splitlines():
        fields=line.split(None,5)
        if len(fields)!=6:continue
        span,permissions,offset,device,inode,path=fields
        if not path.startswith('/home/ubuntu/') or '.so' not in path:continue
        identity=(device,inode,path)
        if identity in seen:continue
        seen.add(identity)
        result.append({'mapping':span,'device':device,'inode':int(inode),
                       'path':path,'deleted':path.endswith(' (deleted)')})
    return result

def mapped_libraries(directory):
    try:entries=parse_project_mappings((directory/'maps').read_text())
    except OSError as exc:return {'error':str(exc)}
    for entry in entries:
        # map_files follows the mapped inode, including unlinked old versions.
        # Linux may deny access even when maps itself is readable: preserve the
        # error instead of substituting the current on-disk file's hash.
        entry['mapped_backing_file_sha256']=digest(directory/'map_files'/entry['mapping'])
        disk=Path(entry['path'][:-10] if entry['deleted'] else entry['path'])
        entry['disk_sha256']=digest(disk)
        try:
            stat=disk.stat()
            major,minor=entry['device'].split(':')
            entry['disk_identity_matches_mapping']=(stat.st_ino==entry['inode'] and
                os.major(stat.st_dev)==int(major,16) and os.minor(stat.st_dev)==int(minor,16))
        except OSError:entry['disk_identity_matches_mapping']=False
    return entries

def digest(path):
    try:
        h=hashlib.sha256()
        with open(path,'rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
        return h.hexdigest()
    except OSError as exc: return {'error':str(exc)}

def collect():
    output={'captured_unix':time.time(), 'processes':[], 'workspaces':{}, 'locks':[]}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit(): continue
        try:
            comm=(directory/'comm').read_text().strip()
            args=(directory/'cmdline').read_bytes().split(b'\0')
            # Only record relevant processes, never dump unrelated process arguments/env.
            joined=b' '.join(args)
            if not any(s in joined for s in (b'bt_ros',b'ego_planner_node',b'traj_server',b'run_formal_trial',b'AgentContestMap.py')): continue
            relevant=[a.decode(errors='replace') for a in args if a.startswith((b'__name:=',b'__log:=',b'/home/ubuntu/')) and b'password' not in a.lower()]
            env=dict(x.split(b'=',1) for x in (directory/'environ').read_bytes().split(b'\0') if b'=' in x)
            output['processes'].append({'pid':int(directory.name),'comm':comm,
                'executable':os.readlink(directory/'exe'),'loaded_executable_sha256':digest(directory/'exe'),
                'cwd':os.readlink(directory/'cwd'),'paths':relevant,
                'mapped_project_libraries':mapped_libraries(directory),
                'ros_env':{k:env[k.encode()].decode(errors='replace') for k in
                    ('ROS_PACKAGE_PATH','CMAKE_PREFIX_PATH','ROS_MASTER_URI') if k.encode() in env}})
        except (OSError,ValueError) as exc:
            output.setdefault('process_read_errors',[]).append({'pid':directory.name,'error':str(exc)})
    relatives=['devel/lib/mission_pkg/bt_ros','devel/lib/ego_planner/ego_planner_node',
       'devel/lib/ego_planner/traj_server','src/mission_pkg/src/bt_ros.cpp',
       'src/mission_pkg/src/nodes/action/visual_servo.cpp','src/mission_pkg/launch/llm_mission.launch',
       'src/ego-planner/src/planner/plan_manage/launch/FS-J310/FS-J310_ego-planner.launch']
    for root in (Path('/home/ubuntu/catkin_ws'),Path('/home/ubuntu/cicc_v1_stage_20261005')):
        output['workspaces'][str(root)]={r:digest(root/r) for r in relatives if (root/r).is_file()}
    for p in Path('/tmp').glob('tcei*lock*'):
        output['locks'].append({'path':str(p),'mtime':p.stat().st_mtime})
    p=Path('/home/ubuntu/tcei_baseline_tools/results/baseline_runs.csv')
    if p.exists():
        output['last_trial_csv_mtime']=p.stat().st_mtime
        output['last_trial_rows']=p.read_text(errors='replace').splitlines()[-3:]
    return output

if __name__=='__main__': print(json.dumps(collect(),indent=2))
