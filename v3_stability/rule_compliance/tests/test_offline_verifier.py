"""Regression tests for offline release gating and result accounting."""
import argparse
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools/verify_sequential_offline.py'
SPEC = importlib.util.spec_from_file_location('offline_verifier', SOURCE)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class OfflineVerifierTests(unittest.TestCase):
    def report(self, summary, manifest_code=0):
        def execute(argv, cwd, timeout):
            output = ''
            code = 0
            if any(str(item).endswith('prepare_sequential_deployment.py') for item in argv):
                code = manifest_code
            if '-c' in argv:
                output = summary
            return {'returncode': code, 'stdout': output, 'stderr': ''}
        args = argparse.Namespace(root=SOURCE.parents[1], python=None, compiler=None, timeout=1)
        with patch.object(verifier, 'execute', side_effect=execute), \
                patch.object(verifier, 'find_compiler', return_value=Path('compiler')):
            return verifier.run_all(args)

    def summary(self, **overrides):
        counts = dict(run=3, failed=0, errors=0, skipped=0,
                      expected_failures=0, unexpected_successes=0)
        counts.update(overrides)
        return 'OFFLINE_UNITTEST_JSON=' + json.dumps(counts)

    def test_skip_prevents_release_pass(self):
        report = self.report(self.summary(skipped=1))
        self.assertFalse(report['passed'])
        self.assertEqual(report['counts']['skipped'], 1)

    def test_missing_or_truncated_summary_fails(self):
        self.assertFalse(self.report('ordinary test output')['passed'])
        self.assertFalse(self.report('OFFLINE_UNITTEST_JSON={"run":')['passed'])

    def test_expected_failure_prevents_release_pass(self):
        self.assertFalse(self.report(self.summary(expected_failures=1))['passed'])

    def test_manifest_failure_prevents_release_pass(self):
        report = self.report(self.summary(), manifest_code=1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['results'][0]['name'], 'frozen_release_manifest')

    def test_complete_success_counts_individual_tests(self):
        report = self.report(self.summary())
        self.assertTrue(report['passed'])
        self.assertEqual(report['counts'], dict(passed=9, failed=0, skipped=0))

    def test_cpp_compilation_enforces_warnings(self):
        with patch.object(verifier, 'execute', return_value={}) as execute:
            verifier.compile_cpp(Path('zig.exe'), Path('test.cpp'), Path('test.exe'), Path('.'))
        command = execute.call_args[0][0]
        for flag in ('-Wall', '-Wextra', '-Werror'):
            self.assertIn(flag, command)


if __name__ == '__main__':
    unittest.main()
