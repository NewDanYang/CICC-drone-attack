import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools/audit_trial_runtime.py'
SPEC = importlib.util.spec_from_file_location('audit_trial_runtime', SOURCE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class RuntimeAuditTests(unittest.TestCase):
    def test_python38_syntax(self):
        ast.parse(SOURCE.read_text(encoding='utf-8'), feature_version=(3, 8))
        ast.parse(audit.PROBE, feature_version=(3, 8))

    def test_missing_binary_fails_without_execution(self):
        with patch.object(audit, 'run') as run:
            passed, detail = audit.plugin_check(Path('/missing/bt_ros'), {})
        self.assertFalse(passed)
        run.assert_not_called()

    def test_old_binary_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'bt_ros'
            binary.write_bytes(b'old executable')
            with patch.object(audit.os, 'access', return_value=True), patch.object(audit, 'run') as run:
                passed, detail = audit.plugin_check(binary, {})
            self.assertFalse(passed)
            self.assertIn('refused', detail)
            run.assert_not_called()

    def test_plugin_exit_zero_without_marker_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'bt_ros'
            binary.write_bytes(audit.MARKER.encode())
            with patch.object(audit.os, 'access', return_value=True), patch.object(audit, 'run', return_value=(0, b'ok', b'')):
                self.assertFalse(audit.plugin_check(binary, {})[0])
            with patch.object(audit.os, 'access', return_value=True), patch.object(audit, 'run', return_value=(0, audit.MARKER.encode(), b'')):
                self.assertTrue(audit.plugin_check(binary, {})[0])

    def test_artifact_sha256_streams_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plugin.so'
            path.write_bytes(b'abc')
            self.assertEqual(audit.artifact_sha256(path, chunk_size=1),
                             'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')

    def test_missing_new_plugins_fail_and_have_ldd_records(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = Namespace(repo=root, workspace=root, underlay=root, model_dir=root,
                             ros_setup=root / 'setup.bash', sdk_path=None, px4_root=None,
                             sensor_python=Path(sys.executable), system_python=Path(sys.executable))
            with patch.object(audit, 'run', return_value=(127, b'', b'missing')):
                report = audit.audit(args)
            checks = {item['name']: item for item in report['checks']}
            for name in ('goto', 'planning_control', 'target_tracker'):
                self.assertFalse(checks['artifact:' + name + '.so']['passed'])
                self.assertFalse(checks['linked_libraries:' + name + '.so']['passed'])
                if name in ('goto', 'planning_control'):
                    self.assertFalse(checks['plugin_source:src/nodes/action/' + name + '.cpp']['passed'])
            self.assertFalse(checks['plugin_helper:include/nodes/action/goto_ramp.hpp']['passed'])
            self.assertFalse(checks['plugin_source:src/nodes/perception/target_tracker.cpp']['passed'])
            self.assertFalse(checks['plugin_source:include/nodes/perception/target_tracker.h']['passed'])

    def test_timeout_fails(self):
        with patch.object(audit.subprocess, 'run', side_effect=subprocess.TimeoutExpired('cmd', 1)):
            self.assertEqual(audit.run(['cmd'])[0], 124)

    def test_inventory_checks_index_shards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('mission_once.py', 'prompts/mission_prompt.txt', 'FM9G4B-V/config.json',
                         'FM9G4B-V/tokenizer_config.json', 'FM9G4B-V/tokenizer.json', 'FM9G4B-V/model.safetensors'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}')
            self.assertTrue(audit.model_inventory(root)[0])
            (root / 'FM9G4B-V/model.safetensors.index.json').write_text('{"weight_map":{"a":"missing.safetensors"}}')
            self.assertFalse(audit.model_inventory(root)[0])

    def test_repository_counts_missing_and_dirty_without_listing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [(0, b'abc\n', b''), (0, b'missing file\0', b''),
                       (0, b'R  new\0old\0 M modified\0', b''), (0, b'false\n', b'')]
            with patch.object(audit, 'run', side_effect=results):
                passed, detail = audit.repository(Path(tmp))
            self.assertFalse(passed)
            self.assertEqual(detail['tracked_count'], 1)
            self.assertEqual(detail['dirty_count'], 2)
            self.assertEqual(detail['missing_count'], 1)

    def test_shallow_repository_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tracked').write_text('present')
            results = [(0, b'abc\n', b''), (0, b'tracked\0', b''),
                       (0, b'', b''), (0, b'true\n', b'')]
            with patch.object(audit, 'run', side_effect=results):
                passed, detail = audit.repository(root)
            self.assertFalse(passed)
            self.assertEqual(detail['shallow'], 'true')

    def test_aruco_alternate_api_does_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'cv2.py').write_text('class aruco:\n    class DetectorParameters: pass\n')
            passed, detail = audit.python_probe(sys.executable, ['cv2'], 'aruco', dict(audit.os.environ), root)
            self.assertFalse(passed)
            self.assertIn('DetectorParameters_create', detail['capability_error'])

    def test_probe_imports_in_requested_interpreter(self):
        passed, detail = audit.python_probe(sys.executable, ['json'], 'sensor', dict(audit.os.environ))
        self.assertTrue(passed, detail)
        self.assertIn('json', detail['modules'])
        passed, detail = audit.python_probe(sys.executable, ['nonexistent_trial_module_123'], 'sensor', dict(audit.os.environ))
        self.assertFalse(passed)

    def test_probe_blocks_dependency_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bad_import.py').write_text("open('unwanted.txt', 'w').write('bad')")
            passed, detail = audit.python_probe(sys.executable, ['bad_import'], 'sensor', dict(audit.os.environ), root)
            self.assertFalse(passed)
            self.assertFalse((root / 'unwanted.txt').exists())

    def test_cli_missing_essentials_exits_nonzero_and_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            argv = []
            for option in ('repo', 'workspace', 'underlay', 'model-dir', 'sensor-python', 'system-python'):
                argv.extend(['--' + option, str(Path(tmp) / 'absent')])
            argv.extend(['--output', str(output)])
            with patch.object(audit, 'run', return_value=(127, b'', b'missing')):
                self.assertEqual(audit.main(argv), 1)
            import json
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertFalse(report['passed'])
            self.assertTrue(report['warnings'])


if __name__ == '__main__':
    unittest.main()
