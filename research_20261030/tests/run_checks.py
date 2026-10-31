"""Build real upstream algorithms with explicit ROS/map test doubles; no flight.

Linux: python3 run_checks.py --repo REPO --eigen /usr/include/eigen3 --out RESULT
Windows: add --zig PATH/zig.exe (isolated compiler supported).
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--eigen',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--zig',type=Path);ap.add_argument('--cxx',default='g++')
    a=ap.parse_args();repo=a.repo.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    module=repo/'research_20261030';planner=repo/'official_baseline/catkin_ws/src/ego-planner/src/planner'
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env['PYTHONDONTWRITEBYTECODE']='1'
    env.setdefault('ZIG_LOCAL_CACHE_DIR',str(out/'zig-cache'));env.setdefault('ZIG_GLOBAL_CACHE_DIR',str(out/'zig-global'))
    compiler=[str(a.zig.resolve()),'c++'] if a.zig else [a.cxx]
    suffix='.exe' if os.name=='nt' else ''
    manifest={'kind':'offline_only_no_ROS_no_flight','commands':[],'source_sha256':{},'checks':[]}
    def run(name,command,timeout=180):
        start=time.monotonic();r=subprocess.run(list(map(str,command)),env=env,capture_output=True,timeout=timeout)
        (out/(name+'.log')).write_bytes(r.stdout+r.stderr)
        manifest['commands'].append({'name':name,'argv':list(map(str,command)),'exit_code':r.returncode,'seconds':time.monotonic()-start})
        (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
        if r.returncode:raise RuntimeError(name+' failed; see '+str(out/(name+'.log')))
        return r.stdout
    includes=[module/'tests/stubs',a.eigen.resolve()]+[planner/x/'include' for x in ('plan_manage','bspline_opt','path_searching','traj_utils')]
    flags=['-std=c++14','-O2','-Wno-narrowing']+['-I'+str(x) for x in includes]
    spline=planner/'bspline_opt/src/uniform_bspline.cpp'
    full=[planner/'plan_manage/src/planner_manager.cpp',planner/'bspline_opt/src/bspline_optimizer.cpp',spline,
          planner/'path_searching/src/dyn_a_star.cpp',planner/'traj_utils/src/polynomial_traj.cpp']
    for p in full:manifest['source_sha256'][str(p.relative_to(repo))]=hashlib.sha256(p.read_bytes()).hexdigest()
    for name,source,extras in [('core','test_core.cpp',[]),('upstream','test_upstream_bspline.cpp',[spline]),
                               ('manager','benchmark_manager.cpp',full),('replanning','benchmark_replanning.cpp',full)]:
        executable=out/(name+suffix)
        run('build_'+name,compiler+flags+[module/'tests'/source]+extras+['-o',executable])
        if name=='manager':
            run('run_manager',[executable,out/'manager_benchmark.csv'])
            run('run_manager_v1',[executable,out/'manager_v1.csv','v1'])
            run('run_manager_v2',[executable,out/'manager_v2.csv','v2'])
        elif name=='replanning':run('run_replanning',[executable,out/'replanning_benchmark.csv'])
        else:(out/(name+'_result.json')).write_bytes(run('run_'+name,[executable]))
    run('mission_contract',[sys.executable,'-B',module/'tests/test_mission_contract.py'])
    run('runtime_probe_parser',[sys.executable,'-B',module/'tests/test_runtime_probe.py'])
    # Exercise installer and rollback only on a fresh disposable copy.
    isolated=out/'isolated_plan_manage'
    if isolated.exists():raise RuntimeError('Use a new output directory: isolated tree already exists')
    shutil.copytree(planner/'plan_manage',isolated)
    original={str(p.relative_to(isolated)):hashlib.sha256(p.read_bytes()).hexdigest() for p in isolated.rglob('*') if p.is_file()}
    run('install_candidate',[sys.executable,'-B',module/'planner/install_candidate.py',isolated,'--apply'])
    patched_full=[isolated/'src/planner_manager.cpp']+full[1:]
    patched_flags=['-I'+str(isolated/'include')]+flags
    run('build_patched_manager',compiler+patched_flags+[module/'tests/benchmark_manager.cpp']+patched_full+['-o',out/('patched_manager'+suffix)])
    run('run_patched_default_off',[out/('patched_manager'+suffix),out/'patched_default_off.csv'])
    run('run_patched_runtime_on',[out/('patched_manager'+suffix),out/'patched_runtime_on.csv','runtime'])
    run('build_patched_replanning',compiler+patched_flags+[module/'tests/benchmark_replanning.cpp']+patched_full+['-o',out/('patched_replanning'+suffix)])
    run('run_patched_replanning',[out/('patched_replanning'+suffix),out/'patched_replanning.csv','runtime'])
    off=list(csv.DictReader((out/'manager_benchmark.csv').open()))
    on=list(csv.DictReader((out/'patched_runtime_on.csv').open()))
    assert len(off)==len(on)
    matches=0
    for before,after in zip(off,on):
        assert before['success']==after['success']
        # The source-level integration must actually alter the managed trajectory.
        if before['accepted']=='1':
            assert abs(float(before['candidate_s'])-float(after['original_s']))<1e-6,(before,after)
            matches+=1
    manifest['checks'].append({'runtime_selected_trajectories_matching_adapter':matches})
    extended=list(csv.DictReader((out/'replanning_benchmark.csv').open()))
    integrated=list(csv.DictReader((out/'patched_replanning.csv').open()))
    assert len(extended)==len(integrated)==60
    integrated_matches=0
    for before,after in zip(extended,integrated):
        assert before['case']==after['case'] and before['success']==after['success']
        if before['guarded_accepted']=='1':
            # Wall-clock budget can safely fall back on slower hosts. A matched
            # replacement is required at least once; fallback is not a match.
            if abs(float(before['guarded_s'])-float(after['original_s']))<1e-6:integrated_matches+=1
            else:assert abs(float(before['original_s'])-float(after['original_s']))<1e-6
    assert integrated_matches>0,'No runtime integration replacement demonstrated'
    manifest['checks'].append({'extended_runtime_selected_matches':integrated_matches,'synthetic_cases':60})
    run('rollback_candidate',[sys.executable,'-B',module/'planner/install_candidate.py',isolated,'--rollback'])
    for path,digest in original.items():
        assert hashlib.sha256((isolated/path).read_bytes()).hexdigest()==digest,path
    manifest['checks'].append({'installer_rollback_original_files':len(original),'all_hashes_restored':True})
    for path,digest in manifest['source_sha256'].items():
        assert hashlib.sha256((repo/path).read_bytes()).hexdigest()==digest
    manifest['passed']=True
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'passed':True,'results':str(out),'commands':len(manifest['commands'])},indent=2))

if __name__=='__main__':main()
