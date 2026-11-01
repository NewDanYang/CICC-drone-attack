import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools/analyze_sequential_timing.py'
SPEC = importlib.util.spec_from_file_location('analyze_sequential_timing', SOURCE)
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)
EVIDENCE = SOURCE.parents[2] / 'reports/sequential_target_20261023'


def root(stamp, old, new):
    return '[{}]: LLMSequence \x1b[33m{}\x1b[0m -> \x1b[32m{}\x1b[0m\n'.format(stamp, old, new)


def command(start, end=None, body='[Takeoff]: Takeoff start', outcome='SUCCESS'):
    text = root(start, 'IDLE', 'RUNNING') + body + '\n'
    return text + (root(end, 'RUNNING', outcome) if end is not None else '')


class SequentialTimingTests(unittest.TestCase):
    def test_python38_syntax(self):
        ast.parse(SOURCE.read_text(encoding='utf-8'), feature_version=(3, 8))

    def test_actual_trial23c_ansi(self):
        report = timing.analyze((EVIDENCE / 'trial23c_mission.log').read_text(encoding='utf-8'),
                                (EVIDENCE / 'trial23c_model.log').read_text(encoding='utf-8'))
        self.assertTrue(report['summary']['controller_sequence_complete'])
        self.assertTrue(report['model_statuses_correlated'])
        self.assertEqual(report['model_validation_retry_count'], 0)
        self.assertEqual([s['execution_s'] for s in report['stages']],
                         [13.124, 22.496, 4.889, 23.537, 34.832, 11.752])
        self.assertEqual([g['idle_s'] for g in report['idle_gaps']],
                         [12.422, 11.738, 21.311, 6.235, 18.369])
        self.assertEqual(report['summary']['observed_execution_s'], 110.63)
        self.assertEqual(report['summary']['observed_idle_s'], 70.075)
        self.assertEqual(report['summary']['takeoff_start_to_final_land_s'], 180.705)
        self.assertIsNone(report['summary']['airborne_time_s'])
        self.assertEqual(report['stages'][4]['outcome'], 'ATTEMPTED_UNVERIFIED')
        self.assertEqual(report['stages'][4]['model_reason'], 'ATTEMPTED_UNVERIFIED')
        self.assertFalse(report['warnings'])

    def test_actual_trial23b_partial_and_retry(self):
        report = timing.analyze((EVIDENCE / 'trial23b_mission.log').read_text(encoding='utf-8'),
                                (EVIDENCE / 'trial23b_model.log').read_text(encoding='utf-8'))
        self.assertEqual(report['model_validation_retry_count'], 1)
        self.assertFalse(report['summary']['controller_sequence_complete'])
        self.assertEqual(report['stages'][-1]['bt_outcome'], 'INCOMPLETE')
        self.assertIsNone(report['stages'][-1]['execution_s'])
        self.assertIsNone(report['summary']['takeoff_start_to_final_land_s'])

    def test_missing_terminal_not_filled_by_model_success(self):
        model = '[STATUS] ' + json.dumps({'command': 'takeoff', 'request_id': 'a', 'status': 'SUCCESS'})
        report = timing.analyze(command('100.000'), model)
        self.assertEqual(report['stages'][0]['outcome'], 'INCOMPLETE')
        self.assertIsNone(report['stages'][0]['execution_s'])

    def test_clock_backwards_does_not_create_duration(self):
        report = timing.analyze(command('100.000', '90.000'))
        self.assertIsNone(report['stages'][0]['execution_s'])
        self.assertTrue(report['warnings'])

    def test_clock_reset_between_commands_does_not_create_idle_or_span(self):
        report = timing.analyze(command('100', '110') + command('20', '25', '[Land]: landed'))
        self.assertIsNone(report['idle_gaps'][0]['idle_s'])
        self.assertIsNone(report['summary']['takeoff_start_to_final_land_s'])

    def test_restart_with_increasing_clock_does_not_bridge(self):
        report = timing.analyze(command('100', '110') +
                                '[INFO] [120]: === Behavior Tree Mission Node Started ===\n' +
                                command('130', '140', '[Land]: Landed and disarmed.'))
        self.assertIsNone(report['idle_gaps'][0]['idle_s'])
        self.assertIsNone(report['summary']['takeoff_start_to_final_land_s'])

    def test_restart_interrupts_running(self):
        report = timing.analyze(command('100') +
                                'Sequential protocol ready on /mission_request; epoch=new\n' +
                                root('120', 'RUNNING', 'SUCCESS'))
        self.assertIsNone(report['stages'][0]['execution_s'])

    def test_orphan_terminal_and_new_start_preserve_incomplete(self):
        report = timing.analyze(root('80', 'RUNNING', 'SUCCESS') + command('100') +
                                command('120', '130', 'TargetLocator square_frame'))
        self.assertEqual(report['stages'][0]['outcome'], 'INCOMPLETE')
        self.assertIsNone(report['idle_gaps'][0]['idle_s'])
        self.assertEqual(report['stages'][1]['execution_s'], 10)

    def test_failure_and_untimestamped_logs(self):
        report = timing.analyze(command('100', '105', outcome='FAILURE'))
        self.assertEqual(report['stages'][0]['outcome'], 'FAILURE')
        self.assertFalse(report['summary']['controller_sequence_complete'])
        self.assertEqual(timing.analyze('[Takeoff]: completed')['stages'], [])

    def test_buffered_header_times_do_not_reset_bt_clock(self):
        text = command('100', '110') + '[INFO] [90]: delayed output\n' + command('120', '130', '[Land]')
        report = timing.analyze(text)
        self.assertEqual(report['idle_gaps'][0]['idle_s'], 10)
        self.assertEqual(report['summary']['takeoff_start_to_final_land_s'], 30)

    def test_partial_model_alignment_cannot_shift_commands(self):
        model = '[STATUS] ' + json.dumps({'command': 'land', 'request_id': 'a', 'status': 'ACCEPTED'})
        report = timing.analyze(command('100', '110'), model)
        self.assertFalse(report['model_statuses_correlated'])
        self.assertEqual(report['stages'][0]['command'], 'takeoff')

    def test_retry_count_and_malformed_json(self):
        report = timing.analyze('', '[命令校验] 第1次生成不合格：bad\n[命令校验] 重试时间预算用完\n[STATUS] {')
        self.assertEqual(report['model_validation_retry_count'], 1)
        self.assertTrue(report['warnings'])

    def test_missing_bag_dependency_is_explicit(self):
        with patch.dict(sys.modules, {'rosbags': None, 'rosbags.highlevel': None}):
            report = timing.bag_evidence(EVIDENCE / 'trial23b.bag')
        self.assertIsNone(report['airborne_time_s'])
        self.assertIn('not installed', report['reason'])

    def test_cli_stdout_and_optional_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mission = Path(tmp) / 'mission.log'
            output = Path(tmp) / 'output.json'
            mission.write_text(command('100', '110'), encoding='utf-8')
            args = [sys.executable, '-B', str(SOURCE), '--mission-log', str(mission)]
            result = subprocess.run(args, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(result.stdout)['stages'][0]['execution_s'], 10)
            result = subprocess.run(args + ['--output', str(output)], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, '')
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['stages'][0]['execution_s'], 10)


if __name__ == '__main__':
    unittest.main()
