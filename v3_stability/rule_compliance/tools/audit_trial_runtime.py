#!/usr/bin/env python3
"""Read-only Ubuntu dependency audit; never starts ROS nodes or loads model weights.

Source ROS, underlay and isolated overlay setup.bash in the calling shell first.
Only the explicitly requested JSON output is written by this tool.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

MARKER = 'sequential_plugin_preflight_passed=1'
LIMIT = 6000


def run(argv, env=None, cwd=None, timeout=20):
    try:
        p = subprocess.run([str(x) for x in argv], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, env=env, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, b'', str(exc).encode('utf-8', 'replace')


def text(value):
    return value.decode('utf-8', 'replace')[-LIMIT:]


def plugin_check(binary, env):
    if not binary.is_file() or not os.access(str(binary), os.X_OK):
        return False, 'missing executable: ' + str(binary)
    # Old bt_ros ignores unknown arguments and can enter normal node startup.
    with binary.open('rb') as stream:
        tail = b''
        found = False
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            if MARKER.encode() in tail + block:
                found = True
                break
            tail = block[-len(MARKER):]
    if not found:
        return False, 'binary lacks safe preflight marker; refused execution'
    code, out, err = run([binary, '--check-plugins'], env=env, timeout=15)
    return code == 0 and MARKER in text(out).splitlines(), {
        'returncode': code, 'stdout': text(out), 'stderr': text(err)}


def repository(repo):
    code, out, err = run(['git', '-C', repo, 'rev-parse', 'HEAD'])
    if code:
        return False, {'error': text(err)}
    revision = text(out).strip()
    code, out, err = run(['git', '-C', repo, 'ls-files', '-z'])
    files = [os.fsdecode(x) for x in out.split(b'\0') if x]
    missing = [x for x in files if not (repo / x).exists()]
    status, dirty, error = run(['git', '-C', repo, 'status', '--porcelain=v1', '-z',
                                '--untracked-files=normal'])
    entries = dirty.split(b'\0')
    count = 0
    i = 0
    while i < len(entries):
        entry = entries[i]
        if entry:
            count += 1
            if entry[:1] in (b'R', b'C') or entry[1:2] in (b'R', b'C'):
                i += 1
        i += 1
    shallow_code, shallow_out, shallow_err = run(['git', '-C', repo, 'rev-parse', '--is-shallow-repository'])
    shallow = text(shallow_out).strip()
    return code == 0 and status == 0 and shallow_code == 0 and shallow == 'false' and bool(files) and not missing, {
        'revision': revision, 'shallow': shallow, 'history_error': text(shallow_err), 'tracked_count': len(files), 'missing_count': len(missing),
        'missing_sample': missing[:50], 'dirty_count': count,
        'error': text(err + error)}


PROBE = r'''
import importlib, json, os, sys
def readonly(event, args):
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            raise PermissionError('audit blocks dependency file writes')
    if event in ('os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.chmod', 'os.chown', 'os.truncate', 'os.symlink', 'os.link'):
        raise PermissionError('audit blocks dependency filesystem mutation')
sys.addaudithook(readonly)
result = {'interpreter': sys.executable, 'modules': {}}
ok = True
for name in json.loads(sys.argv[1]):
    try:
        mod = importlib.import_module(name)
        result['modules'][name] = {'file': getattr(mod, '__file__', None), 'version': str(getattr(mod, '__version__', 'unknown'))}
    except Exception as exc:
        ok = False
        result['modules'][name] = {'error': str(exc)}
mode = sys.argv[2]
try:
    if mode == 'model':
        import torch
        result['cuda'] = bool(torch.cuda.is_available())
        check = getattr(torch.cuda, 'is_bf16_supported', None)
        result['bf16'] = bool(check()) if check and result['cuda'] else None
        ok = ok and result['cuda'] and result['bf16'] is not False
    if mode == 'aruco':
        import cv2
        a = cv2.aruco
        result['aruco_apis'] = {n: hasattr(a, n) for n in ('getPredefinedDictionary', 'DetectorParameters_create', 'DetectorParameters', 'detectMarkers', 'ArucoDetector', 'DICT_ARUCO_ORIGINAL')}
        p = a.DetectorParameters_create()
        p.cornerRefinementMethod = a.CORNER_REFINE_SUBPIX
        d = a.getPredefinedDictionary(a.DICT_ARUCO_ORIGINAL)
        assert callable(a.detectMarkers)
        assert callable(a.drawDetectedMarkers)
except Exception as exc:
    ok = False
    result['capability_error'] = str(exc)
print('AUDIT_JSON=' + json.dumps(result))
sys.exit(0 if ok else 1)
'''


def python_probe(interpreter, modules, mode, env, cwd=None):
    code, out, err = run([interpreter, '-B', '-c', PROBE, json.dumps(modules), mode],
                         env=env, cwd=cwd, timeout=45)
    for line in text(out).splitlines():
        if line.startswith('AUDIT_JSON='):
            result = json.loads(line[len('AUDIT_JSON='):])
            result['stderr'] = text(err)
            return code == 0, result
    return False, {'returncode': code, 'stdout': text(out), 'stderr': text(err)}


def artifact_sha256(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b''):
            digest.update(chunk)
    return digest.hexdigest()


def model_inventory(root):
    model = root / 'FM9G4B-V'
    required = [root / 'mission_once.py', root / 'prompts/mission_prompt.txt',
                model / 'config.json', model / 'tokenizer_config.json']
    weights = list(model.glob('*.safetensors')) + list(model.glob('pytorch_model*.bin'))
    tokenizer = [model / n for n in ('tokenizer.json', 'tokenizer.model', 'vocab.json')
                 if (model / n).is_file()]
    required += weights + tokenizer
    missing = [str(p) for p in required if not p.is_file() or p.stat().st_size == 0]
    indices = list(model.glob('*.index.json'))
    errors = []
    for index in indices:
        try:
            data = json.loads(index.read_text(encoding='utf-8'))
            for name in set(data['weight_map'].values()):
                shard = (model / name).resolve()
                if model.resolve() not in shard.parents or not shard.is_file() or not shard.stat().st_size:
                    errors.append('missing or invalid shard: ' + name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    return not missing and bool(weights) and bool(tokenizer) and not errors, {
        'missing': missing, 'weight_file_count': len(weights), 'tokenizer_files': [p.name for p in tokenizer],
        'index_errors': errors, 'weight_bytes': sum(p.stat().st_size for p in weights)}


def audit(args):
    checks = []
    def add(name, passed, detail):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1', YOLO_AUTOINSTALL='false', GIT_OPTIONAL_LOCKS='0')
    add('ubuntu', platform.system() == 'Linux' and Path('/etc/os-release').is_file()
        and 'ID=ubuntu' in Path('/etc/os-release').read_text(), platform.platform())
    for exe in ('git', 'cmake', 'g++', 'catkin_make', 'ffmpeg', 'ffprobe', 'ldd'):
        add('executable:' + exe, shutil.which(exe) is not None, shutil.which(exe))
    add('repository', *repository(args.repo))
    manifest = args.repo / 'v3_stability/rule_compliance/deploy/sequential_release_manifest.json'
    try:
        payloads = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(payloads, dict) or not payloads:
            raise ValueError('manifest must contain payload hashes')
        for relative, expected in payloads.items():
            path = (args.repo / relative).resolve()
            valid = args.repo.resolve() in path.parents and path.is_file()
            actual = artifact_sha256(path) if valid else None
            add('release_payload:' + relative, valid and actual == expected,
                {'path': str(path), 'expected_sha256': expected, 'actual_sha256': actual})
    except (OSError, ValueError, TypeError) as exc:
        add('release_manifest', False, str(exc))
    setups = [args.ros_setup, args.underlay / 'devel/setup.bash', args.workspace / 'devel/setup.bash']
    for setup in setups:
        add('setup:' + str(setup), setup.is_file(), str(setup))
    prefixes = os.environ.get('CMAKE_PREFIX_PATH', '').split(os.pathsep)
    expected = [str(args.workspace / 'devel'), str(args.underlay / 'devel')]
    add('sourced_overlay', all(p in prefixes for p in expected) and
        prefixes.index(expected[0]) < prefixes.index(expected[1]) if all(p in prefixes for p in expected) else False,
        {'expected_order': expected, 'actual': prefixes})
    binary = args.workspace / 'devel/lib/mission_pkg/bt_ros'
    artifacts = [binary]
    plugin_specs = (
        ('wait_for_stable_position', 'src/nodes/action/wait_for_stable_position.cpp', 'include/nodes/action/wait_for_stable_position.h'),
        ('visual_servo', 'src/nodes/action/visual_servo.cpp', 'include/nodes/action/visual_servo.h'),
        ('goto', 'src/nodes/action/goto.cpp', 'include/nodes/action/goto.h'),
        ('planning_control', 'src/nodes/action/planning_control.cpp', 'include/nodes/action/planning_control.h'),
        ('target_tracker', 'src/nodes/perception/target_tracker.cpp', 'include/nodes/perception/target_tracker.h'),
    )
    for stem, source_rel, header_rel in plugin_specs:
        for relative in (source_rel, header_rel):
            p = args.workspace / 'src/mission_pkg' / relative
            add('plugin_source:' + relative, p.is_file(), str(p))
        artifacts.append(args.workspace / ('devel/lib/' + stem + '.so'))
    for helper in ('src/bt_ros.cpp', 'include/nodes/action/goto_ramp.hpp', 'include/sequence_session.hpp'):
        p = args.workspace / 'src/mission_pkg' / helper
        add('plugin_helper:' + helper, p.is_file(), str(p))
    for artifact in artifacts:
        exists = artifact.is_file()
        add('artifact:' + artifact.name, exists, str(artifact))
        if exists:
            add('artifact_sha256:' + artifact.name, True, artifact_sha256(artifact))
        code, out, err = run(['ldd', artifact], env=env, timeout=10) if exists else (1, b'', b'missing artifact')
        add('linked_libraries:' + artifact.name, code == 0 and b'not found' not in out + err,
            {'returncode': code, 'output': text(out + err)})
    add('plugin_preflight', *plugin_check(binary, env))
    sdk = args.sdk_path or (args.px4_root / 'RflySimAPIs/RflySimSDK' if args.px4_root else None)
    add('sdk_path', sdk is not None and sdk.is_dir(), str(sdk))
    sensor_env = env.copy()
    if sdk:
        paths = [sdk] + [sdk / n for n in ('comm', 'ctrl', 'ue', 'vision', 'phm', 'swarm', 'adb', 'wsl', 'test', 'word')]
        sensor_env['PYTHONPATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + env.get('PYTHONPATH', '')
    sensor = args.underlay / 'src/sensor_pkg'
    add('sensor_imports', *python_probe(args.sensor_python, ['cv2', 'numpy', 'scipy', 'pygame', 'rospy',
        'sensor_msgs.point_cloud2', 'nav_msgs.msg', 'VisionCaptureApi', 'ReqCopterSim', 'RflyRosStart',
        'PX4MavCtrlV4', 'UE4CtrlAPI'], 'sensor', sensor_env, sensor))
    add('system_imports_aruco', *python_probe(args.system_python, ['rospy', 'roslaunch', 'rospkg', 'cv2',
        'numpy', 'sensor_msgs.msg', 'nav_msgs.msg', 'mavros_msgs.msg'], 'aruco', env))
    add('model_imports_cuda', *python_probe(args.sensor_python, ['torch', 'transformers', 'PIL'], 'model', env))
    add('model_inventory', *model_inventory(args.model_dir))
    detector = args.underlay / 'src/object_det'
    wrapper = detector / 'scripts/det_color_conda.sh'
    add('detector_wrapper', wrapper.is_file(), str(wrapper))
    detector_env = env.copy()
    detector_env['PYTHONPATH'] = os.pathsep.join(str(detector / p) for p in ('src', 'third_party', 'third_party/CLIP', 'scripts')) + os.pathsep + env.get('PYTHONPATH', '')
    passed, detail = python_probe('/opt/conda/envs/demo/bin/python3', ['torch', 'ultralytics',
        'common_msgs.msg', 'object_det.config', 'object_det.detectors', 'object_det.utils'], 'detector', detector_env)
    vendored = detail.get('modules', {}).get('ultralytics', {}).get('file')
    add('detector_imports', passed and bool(vendored) and
        (detector / 'third_party').resolve() in Path(vendored).resolve().parents, detail)
    weights = list(detector.rglob('best.pt')) if detector.is_dir() else []
    add('detector_weights', any(p.stat().st_size > 0 for p in weights), [str(p) for p in weights])
    for option, token in (('-encoders', 'libx264'), ('-devices', 'x11grab')):
        code, out, err = run(['ffmpeg', '-hide_banner', option], env=env)
        add('recording:' + token, code == 0 and token.encode() in out + err, text(out + err))
    return {'schema_version': 1, 'passed': all(c['passed'] for c in checks), 'checks': checks,
            'warnings': ['No flight, live ROS topics, rendering, model loading/inference, recording session, or build tested.',
                         'Run from a shell with ROS + underlay + isolated overlay sourced; import hooks are trusted runtime code.',
                         'CUDA BF16 is unknown on older torch versions without is_bf16_supported; inspect model_imports_cuda.',
                         'Detector imports use /opt/conda/envs/demo/bin/python3; wrapper conda selection/fallback is not executed or verified.',
                         'Non-shallow history is checked; remote branch completeness and Git LFS payload integrity are not established.',
                         'Dependency presence does not establish full runtime or trial readiness.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'workspace', 'underlay', 'model-dir', 'sensor-python', 'system-python', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--px4-root', type=Path)
    parser.add_argument('--sdk-path', type=Path)
    parser.add_argument('--ros-setup', type=Path, default=Path('/opt/ros/noetic/setup.bash'))
    args = parser.parse_args(argv)
    for name in ('repo', 'workspace', 'underlay', 'model_dir', 'sensor_python', 'system_python', 'output', 'px4_root', 'sdk_path', 'ros_setup'):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    report = audit(args)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'output': str(args.output)}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
