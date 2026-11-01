#!/usr/bin/env python3
"""Run the offline sequential-release verification without ROS or network access."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


def execute(argv, cwd, timeout):
    try:
        completed = subprocess.run([str(item) for item in argv], cwd=str(cwd),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        return {'returncode': completed.returncode,
                'stdout': completed.stdout.decode('utf-8', 'replace')[-8000:],
                'stderr': completed.stderr.decode('utf-8', 'replace')[-8000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'returncode': 124, 'stdout': '', 'stderr': str(exc)}


def version(executable, cwd):
    flag = 'version' if Path(executable).stem.lower() == 'zig' else '--version'
    result = execute([executable, flag], cwd, 10)
    return {'executable': str(executable), **result}


def test_result(name, result, skipped=False):
    return {'name': name, 'status': 'skipped' if skipped else ('passed' if result['returncode'] == 0 else 'failed'), **result}


def find_compiler(root, requested):
    if requested or os.environ.get('CXX'):
        return Path(requested or os.environ['CXX'])
    repository = root.parents[1]
    bundled = sorted((repository / '.local-toolchain').glob('zig-*/zig.exe'))
    if bundled:
        return bundled[0]
    found = shutil.which('zig') or shutil.which('c++') or shutil.which('g++')
    return Path(found) if found else None


def compile_cpp(compiler, source, output, cwd):
    if not compiler:
        return {'returncode': 127, 'stdout': '', 'stderr': 'no C++ compiler found'}
    name = compiler.name.lower()
    if name == 'zig.exe' or name == 'zig':
        command = [compiler, 'c++', source, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-O0', '-o', output]
    else:
        command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-O0', source, '-o', output]
    return execute(command, cwd, 90)


def run_all(args):
    root = args.root.resolve()
    portable_cmake = sorted((root.parents[1] / '.local-toolchain').glob('cmake-*/bin/cmake.exe'))
    if not shutil.which('cmake') and portable_cmake:
        os.environ['PATH'] = str(portable_cmake[0].parent) + os.pathsep + os.environ.get('PATH', '')
    portable_ninja = sorted((root.parents[1] / '.local-toolchain').glob('ninja-*/ninja.exe'))
    if not shutil.which('ninja') and portable_ninja:
        os.environ['PATH'] = str(portable_ninja[0].parent) + os.pathsep + os.environ.get('PATH', '')
    tests = root / 'tests'
    results = []
    python = Path(args.python or sys.executable)
    manifest_check = execute([python, '-B', root / 'tools/prepare_sequential_deployment.py',
                              '--expected-manifest', root / 'deploy/sequential_release_manifest.json'],
                             root, args.timeout)
    results.append(test_result('frozen_release_manifest', manifest_check))
    discovery_code = '''
import json, sys, unittest
loader = unittest.TestLoader()
match = loader._match_path
loader._match_path = lambda path, full_path, pattern: path != 'test_aruco_display_loop.py' and match(path, full_path, pattern)
suite = loader.discover(sys.argv[1], pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
print('OFFLINE_UNITTEST_JSON=' + json.dumps({'run': result.testsRun, 'failed': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures), 'unexpected_successes': len(result.unexpectedSuccesses)}))
sys.exit(0 if result.wasSuccessful() else 1)
'''
    discovery = execute([python, '-B', '-c', discovery_code, tests], root, args.timeout)
    results.append(test_result('python_unittest_discover', discovery))
    aruco = execute([python, tests / 'test_aruco_display_loop.py'], root, args.timeout)
    results.append(test_result('test_aruco_display_loop.py', aruco))

    compiler = find_compiler(root, args.compiler)
    cmake = shutil.which('cmake')
    tools = {'python': version(python, root), 'compiler': version(compiler, root) if compiler else None,
             'cmake': version(cmake, root) if cmake else None,
             'ninja': version(shutil.which('ninja'), root) if shutil.which('ninja') else None}
    for source in ('sequence_session_test.cpp', 'goto_ramp_test.cpp'):
        with tempfile.TemporaryDirectory(prefix='offline-cxx-') as temp:
            output = Path(temp) / (Path(source).stem + ('.exe' if os.name == 'nt' else ''))
            built = compile_cpp(compiler, tests / source, output, root)
            results.append(test_result(source + ':compile', built))
            if built['returncode'] == 0:
                ran = execute([output], root, args.timeout)
                results.append(test_result(source + ':run', ran))

    counts = {status: sum(item['status'] == status for item in results
                          if item['name'] != 'python_unittest_discover')
              for status in ('passed', 'failed', 'skipped')}
    unittest_counts = None
    for line in discovery['stdout'].splitlines():
        if line.startswith('OFFLINE_UNITTEST_JSON='):
            try:
                unittest_counts = json.loads(line.split('=', 1)[1])
            except ValueError:
                unittest_counts = None
    if unittest_counts is None:
        counts['failed'] += 1
    else:
        counts['passed'] += (unittest_counts['run'] - unittest_counts['failed'] -
                             unittest_counts['errors'] - unittest_counts['skipped'] -
                             unittest_counts['unexpected_successes'] - unittest_counts['expected_failures'])
        counts['failed'] += (unittest_counts['failed'] + unittest_counts['errors'] +
                             unittest_counts['unexpected_successes'] + unittest_counts['expected_failures'])
        counts['skipped'] += unittest_counts['skipped']
        if discovery['returncode'] != 0 and not counts['failed']:
            counts['failed'] += 1
    report = {'schema_version': 1, 'passed': counts['failed'] == 0 and counts['skipped'] == 0,
              'platform': platform.platform(), 'root': str(root), 'tools': tools,
              'counts': counts, 'results': results,
              'checks': {'standalone_aruco_executed_separately': True,
                         'network_access_requested': False}}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--python')
    parser.add_argument('--compiler')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    report = run_all(args)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding='utf-8')
    print(payload, end='')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
