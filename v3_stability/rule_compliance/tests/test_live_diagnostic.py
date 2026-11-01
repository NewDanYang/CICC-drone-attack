#!/usr/bin/env python3
"""Offline safety and protocol tests; no ROS master or simulator is contacted."""
import importlib.util
import json
import signal
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'run_live_diagnostic.py'
spec = importlib.util.spec_from_file_location('live_diagnostic', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NoVideoTests(unittest.TestCase):
    def test_explicit_skip_never_starts_media_process(self):
        with patch.object(module.subprocess, 'Popen', side_effect=AssertionError('media process forbidden')), \
                patch.object(module.subprocess, 'run', side_effect=AssertionError('media process forbidden')):
            recorder = module.NoVideoRecorder()
            recorder.start()
            self.assertFalse(recorder.check(require_frames=True)['video_recorded'])
            recorder.stop()


class RecorderHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.recorder = module.Recorder(self.root, NS(fps=10, video_size='2560x1494'))
        self.recorder.process = NS(poll=lambda: None, pid=99999999)
        self.recorder.started = 100.
        self.now = 100.
        self.clock = patch.object(module.time, 'monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def sample(self, elapsed, frames, media, incomplete=''):
        self.now = 100 + elapsed
        progress = self.root / 'recorder.progress'
        with progress.open('a') as output:
            output.write('frame={}\nout_time_us={}\nprogress=continue\n{}'.format(
                frames, int(media * 1000000), incomplete))
        return self.recorder.check()

    def test_startup_allows_two_seconds_then_healthy_ten_fps(self):
        self.sample(0, 0, 0)
        self.sample(2, 20, 1.9)
        for second in range(3, 9):
            proof = self.sample(second, second * 10, second - .1)
        self.assertAlmostEqual(proof['rolling_fps'], 10)
        self.assertAlmostEqual(proof['rolling_media_rate'], 1)

    def test_stalled_frame_with_advancing_media_and_fresh_file_fails(self):
        self.sample(2, 20, 1.9)
        self.sample(3, 20, 2.9)
        self.sample(4, 20, 3.9)
        with self.assertRaisesRegex(RuntimeError, 'stopped advancing'):
            self.sample(5, 20, 4.9)

    def test_stalled_media_with_advancing_frames_and_fresh_file_fails(self):
        self.sample(2, 20, 1.9)
        self.sample(3, 30, 1.9)
        self.sample(4, 40, 1.9)
        with self.assertRaisesRegex(RuntimeError, 'stopped advancing'):
            self.sample(5, 50, 1.9)

    def test_repeated_complete_blocks_cannot_refresh_advancement(self):
        self.sample(2, 20, 1.9)
        self.sample(4, 20, 1.9)
        with self.assertRaisesRegex(RuntimeError, 'stopped advancing'):
            self.sample(5, 20, 1.9)

    def test_regressing_frame_or_media_fails_immediately(self):
        for frames, media in ((19, 2.9), (30, 1.8)):
            with self.subTest(frames=frames, media=media):
                self.recorder.previous_progress = None
                self.recorder.progress_samples = []
                self.sample(2, 20, 1.9)
                with self.assertRaisesRegex(RuntimeError, 'regressed'):
                    self.sample(3, frames, media)

    def test_low_cadence_fails_despite_high_cumulative_fps(self):
        self.sample(2, 200, 20)
        self.sample(3, 204, 21)
        self.sample(4, 208, 22)
        with self.assertRaisesRegex(RuntimeError, 'sustained'):
            self.sample(5, 212, 23)

    def test_low_media_cadence_fails_despite_advancing_frames(self):
        self.sample(2, 20, 2)
        self.sample(3, 30, 2.4)
        self.sample(4, 40, 2.8)
        with self.assertRaisesRegex(RuntimeError, 'sustained'):
            self.sample(5, 50, 3.2)

    def test_half_requested_rate_is_allowed_after_three_second_window(self):
        self.sample(2, 20, 2)
        self.sample(3, 25, 2.5)
        self.sample(4, 30, 3)
        self.assertEqual(self.sample(5, 35, 3.5)['rolling_fps'], 5)

    def test_rolling_window_discards_old_fast_frames(self):
        for second in range(2, 7):
            self.sample(second, 10 * second, second)
        self.sample(7, 64, 7)
        self.sample(8, 68, 8)
        with self.assertRaisesRegex(RuntimeError, 'sustained'):
            self.sample(9, 72, 9)

    def test_incomplete_block_does_not_regress_last_complete_sample(self):
        self.sample(2, 20, 1.9)
        proof = self.sample(3, 30, 2.9, 'frame=1\nout_time_us=0\n')
        self.assertEqual(proof['frames'], 30)
        self.assertEqual(proof['media_seconds'], 2.9)

    def test_out_time_text_and_legacy_microseconds_are_supported(self):
        for field, value in (('out_time', '00:00:01.900000'), ('out_time_ms', '1900000')):
            with self.subTest(field=field):
                self.recorder.previous_progress = None
                self.recorder.progress_samples = []
                self.now = 102
                (self.root / 'recorder.progress').write_text(
                    'frame=20\n{}={}\nprogress=continue\n'.format(field, value))
                self.assertEqual(self.recorder.check()['media_seconds'], 1.9)

    def finalize(self, duration, decode):
        self.recorder.process = NS(poll=lambda: 0, returncode=0)
        probe = NS(stdout=json.dumps({'streams': [{'nb_read_frames': '50'}],
                                     'format': {'duration': str(duration)}}))
        with patch.object(module.subprocess, 'run', side_effect=[probe, decode]) as run:
            self.recorder.stop()
        return run

    def test_stop_decodes_entire_file_with_duration_scaled_bounded_timeout(self):
        for duration, timeout in ((6, 15), (60, 30), (600, 120)):
            with self.subTest(duration=duration):
                run = self.finalize(duration, NS(stderr=''))
                probe, decode = run.call_args_list
                self.assertIn('0%+5', probe.args[0])
                command = decode.args[0]
                self.assertEqual(command[0], 'ffmpeg')
                self.assertIn('-xerror', command)
                self.assertEqual(command[-3:], ['-f', 'null', module.os.devnull])
                self.assertNotIn('-t', command)
                self.assertNotIn('-read_intervals', command)
                self.assertEqual(decode.kwargs['timeout'], timeout)
                self.assertTrue(self.recorder.proof['full_file_decode']['passed'])

    def test_full_file_decode_failure_rejected_after_successful_probe(self):
        failure = module.subprocess.CalledProcessError(1, ['ffmpeg'], stderr='corrupt later frame')
        with self.assertRaises(module.subprocess.CalledProcessError):
            self.finalize(600, failure)
        self.assertNotIn('full_file_decode', self.recorder.proof)

    def test_full_file_decode_error_output_and_timeout_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'full-file decode failed'):
            self.finalize(6, NS(stderr='corrupt later frame'))
        with self.assertRaises(module.subprocess.TimeoutExpired):
            self.finalize(600, module.subprocess.TimeoutExpired(['ffmpeg'], 120))


class FakeRecorder:
    def __init__(self, fail=False):
        self.fail, self.proof = fail, {}

    def start(self):
        pass

    def check(self, require_frames=False):
        if self.fail and require_frames:
            raise RuntimeError('recording failed before flight')
        return {'frames': 20, 'observed_fps': 10}

    def stop(self):
        pass


class FakeROS:
    State = Odometry = object
    String = NS

    def __init__(self):
        self.t, self.armed, self.z = 100., False, 0.
        self.mode = 'POSCTL'
        self.callbacks, self.sent, self.mode_calls = {}, [], []
        self.reject = False
        self.drop = False
        self.initialized = False
        self.unregistered = []

    def now(self):
        return self.t

    def init_node(self, *args, **kwargs):
        if not kwargs.get('disable_signals', False):
            signal.signal(signal.SIGINT, signal.default_int_handler)
        self.initialized = True

    def is_shutdown(self):
        return False

    def Subscriber(self, topic, kind, callback):
        self.callbacks[topic] = callback
        self.refresh()
        return NS(unregister=lambda: self.unregistered.append(topic))

    def refresh(self):
        stamp = self.t
        header = NS(stamp=NS(to_sec=lambda: stamp))
        messages = {
            '/mavros/state': NS(header=header, connected=True, armed=self.armed, mode=self.mode),
            '/rflysim/uav1/local/odom': NS(header=header, pose=NS(pose=NS(position=NS(x=0., y=0., z=self.z)))),
            '/mission_ready': NS(data=json.dumps({'protocol': 1, 'server_epoch': 'epoch', 'state': 'IDLE'}))}
        for topic, callback in list(self.callbacks.items()):
            if topic in messages:
                callback(messages[topic])

    def sleep(self, seconds):
        self.t += seconds
        self.refresh()

    def Publisher(self, topic, kind, **kwargs):
        return NS(get_num_connections=lambda: 1, publish=lambda msg: self.publish(topic, msg))

    def publish(self, topic, msg):
        payload = json.loads(msg.data)
        self.sent.append((topic, payload))
        if topic != '/mission_request' or self.drop:
            return
        command = payload.get('command', '')
        row = {**payload, 'command': command, 'status': 'ACCEPTED'}
        callback = self.callbacks['/mission_status']
        if self.reject and command == 'takeoff':
            callback(NS(data=json.dumps({**row, 'status': 'REJECTED', 'reason': 'disarmed AUTO.LAND'})))
            return
        callback(NS(data=json.dumps(row)))
        if command == 'takeoff':
            self.armed, self.z, self.mode = True, 1., 'OFFBOARD'
        elif command == 'land':
            self.armed, self.z = False, 0.
        self.t += .001
        self.refresh()
        callback(NS(data=json.dumps({**row, 'status': 'SUCCESS'})))

    def land(self):
        self.mode_calls.append('AUTO.LAND')
        self.armed, self.z = False, 0.
        self.sleep(.05)
        return NS(mode_sent=True)


class LiveDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ros = FakeROS()
        self.runner = module.Diagnostic(self.tmp.name, self.ros, FakeRecorder(),
                                        clock=self.ros.now, sleep=self.ros.sleep)
        self.addCleanup(lambda: None if self.runner.closed else self.runner.close())

    def test_reset_takeoff_hover_land(self):
        report = self.runner.run(lambda: {'controller_pid': 42})
        self.assertTrue(report['passed'], report)
        self.assertFalse(report['manual_round_credit'])
        self.assertEqual([p.get('command', 'reset') for _, p in self.ros.sent], ['reset', 'takeoff', 'land'])
        self.assertEqual(len(self.ros.unregistered), 4)
        self.assertFalse(report['final_armed'])
        self.assertEqual(json.loads((Path(self.tmp.name) / 'summary.json').read_text())['passed'], True)

    def test_worker_init_disables_ros_signal_registration_before_publish(self):
        original = self.ros.init_node
        flags = []

        def init(*args, **kwargs):
            self.assertEqual(self.ros.sent, [])
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            flags.append(kwargs.get('disable_signals'))
            original(*args, **kwargs)

        self.ros.init_node = init
        previous = signal.getsignal(signal.SIGINT)
        report = self.runner.run(lambda: {})
        self.assertTrue(report['passed'], report)
        self.assertEqual(flags, [True])
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_init_failure_never_publishes_request(self):
        def init(*args, **kwargs):
            raise RuntimeError('init failed')

        self.ros.init_node = init
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertEqual(self.ros.sent, [])
        self.assertIn('init failed', report['error'])

    def test_main_thread_sigint_enters_recovery_without_resend(self):
        publish = self.ros.publish

        def interrupt_after_takeoff(topic, msg):
            publish(topic, msg)
            if topic == '/mission_request' and json.loads(msg.data).get('command') == 'takeoff':
                signal.raise_signal(signal.SIGINT)

        self.ros.publish = interrupt_after_takeoff
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertIn('interrupted', report['error'])
        self.assertEqual(self.ros.mode_calls, ['AUTO.LAND'])
        requests = [p.get('command', 'reset') for topic, p in self.ros.sent if topic == '/mission_request']
        self.assertEqual(requests, ['reset', 'takeoff'])
        self.assertTrue(report['recovery_disarmed_fresh'])

    def test_missing_master_fails_before_init_and_always_summarizes(self):
        with patch.object(module, 'local_rpc', return_value=NS(getPid=lambda *_: (_ for _ in ()).throw(ConnectionRefusedError()))):
            report = self.runner.run(module.check_master)
        self.assertFalse(report['passed'])
        self.assertFalse(self.ros.initialized)
        self.assertEqual(self.ros.sent, [])
        self.assertTrue((Path(self.tmp.name) / 'summary.json').exists())

    def test_master_must_be_loopback_11311(self):
        for uri in ('http://192.0.2.1:11311', 'http://127.0.0.1:11312'):
            with self.assertRaises(RuntimeError):
                module.local_rpc(uri, 11311)

    def test_rejected_disarmed_does_not_land_or_abort(self):
        self.ros.reject = True
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertIn('disarmed AUTO.LAND', report['error'])
        self.assertEqual(self.ros.mode_calls, [])
        self.assertEqual([p.get('command', 'reset') for _, p in self.ros.sent], ['reset', 'takeoff'])

    def test_fresh_disarmed_auto_land_can_reset_without_preflight_mode_change(self):
        self.ros.mode = 'AUTO.LAND'
        report = self.runner.run(lambda: {})
        self.assertTrue(report['passed'], report)
        self.assertEqual([p.get('command', 'reset') for _, p in self.ros.sent], ['reset', 'takeoff', 'land'])
        self.assertEqual(self.ros.mode_calls, [])

    def test_armed_auto_land_preflight_rejects_commands(self):
        self.ros.mode, self.ros.armed = 'AUTO.LAND', True
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertIn('must begin connected, disarmed, IDLE', report['error'])
        self.assertFalse(any(topic == '/mission_request' for topic, _ in self.ros.sent))

    def test_odometry_expires_before_state_at_controller_limits(self):
        self.runner.connect()
        self.ros.t += 1.1
        self.assertFalse(self.runner.fresh('odom'))
        self.assertTrue(self.runner.fresh('state'))
        self.assertTrue(self.runner.fresh('ready'))
        self.ros.t += 1.5
        self.assertFalse(self.runner.fresh('state'))
        self.assertFalse(self.runner.fresh('ready'))

    def test_recording_failure_stops_before_reset_or_takeoff(self):
        self.runner.recorder = FakeRecorder(fail=True)
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertEqual(self.ros.sent, [])
        self.assertEqual(self.ros.mode_calls, [])

    def test_ongoing_recorder_health_failure_triggers_recovery(self):
        recorder = self.runner.recorder
        check = recorder.check

        def fail_when_armed(require_frames=False):
            if self.ros.armed:
                raise RuntimeError('recording frame/media time stopped advancing')
            return check(require_frames)

        recorder.check = fail_when_armed
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertIn('stopped advancing', report['error'])
        self.assertEqual(self.ros.mode_calls, ['AUTO.LAND'])
        self.assertTrue(report['recovery_disarmed_fresh'])
        self.assertEqual([p.get('command', 'reset') for topic, p in self.ros.sent
                          if topic == '/mission_request'], ['reset', 'takeoff'])

    def test_final_decode_failure_overrides_successful_diagnostic(self):
        def stop():
            raise RuntimeError('final MP4 full-file decode failed')

        self.runner.recorder.stop = stop
        report = self.runner.run(lambda: {})
        self.assertFalse(report['passed'])
        self.assertIn('full-file decode failed', report['recorder_error'])
        self.assertFalse(json.loads((Path(self.tmp.name) / 'summary.json').read_text())['passed'])

    def test_old_epoch_session_and_completed_replay_ignored(self):
        self.runner.epoch = 'epoch'
        self.runner.active = {'request_id': 'current', 'command': 'takeoff'}
        base = {'protocol': 1, 'server_epoch': 'epoch', 'session_id': self.runner.session,
                'request_id': 'current', 'command': 'takeoff', 'status': 'SUCCESS'}
        for changes in ({'server_epoch': 'old'}, {'session_id': 'old'}, {'request_id': 'completed'}, {'command': 'land'}):
            self.runner.message('status', NS(data=json.dumps({**base, **changes})))
        self.assertEqual(self.runner.outcomes, {})
        self.runner.message('status', NS(data=json.dumps(base)))
        self.assertEqual(len(self.runner.outcomes['current']), 1)

    def test_unknown_feedback_retains_identity_without_resend(self):
        self.runner.connect()
        self.runner.epoch = 'epoch'
        self.ros.drop = True
        with self.assertRaisesRegex(RuntimeError, 'identity retained'):
            self.runner.request('takeoff', timeout=.2)
        ident = self.runner.active['request_id']
        self.runner.recovery('timeout')
        self.assertEqual(self.runner.active['request_id'], ident)
        self.assertEqual(len(self.ros.sent), 1)
        self.assertEqual(self.ros.mode_calls, [])

    def test_accepted_active_request_can_abort_with_same_identity(self):
        self.runner.connect()
        self.runner.epoch = 'epoch'
        self.runner.active = {'request_id': 'active', 'command': 'takeoff'}
        self.runner.accepted = True
        self.runner.recovery('test')
        self.assertEqual(self.ros.sent[0][0], '/mission_abort')
        self.assertEqual(self.ros.sent[0][1]['request_id'], 'active')
        self.assertEqual(self.ros.mode_calls, [])

    def test_source_replay_and_nonfinite_odom_do_not_refresh_receipt(self):
        self.runner.connect()
        sample = dict(self.runner.samples['odom'])
        self.ros.t += 3
        self.runner.telemetry('odom', sample['message'])
        self.assertFalse(self.runner.fresh('odom'))
        header = NS(stamp=NS(to_sec=lambda: self.ros.t))
        self.runner.telemetry('odom', NS(header=header, pose=NS(pose=NS(position=NS(x=float('nan'), y=0, z=0)))))
        self.assertEqual(self.runner.samples['odom']['receipt'], sample['receipt'])

    def test_service_worker_is_bounded_and_never_retried(self):
        gate = threading.Event()
        calls = []

        def stuck():
            calls.append(1)
            gate.wait(1)

        try:
            with self.assertRaisesRegex(RuntimeError, 'must not be resent'):
                module.bounded_call(stuck, .01)
            self.assertEqual(calls, [1])
        finally:
            gate.set()

    def test_cli_missing_master_writes_summary_without_ros_import(self):
        output = Path(self.tmp.name) / 'cli'
        with patch.object(module, 'check_master', side_effect=RuntimeError('master unavailable')), \
                patch.object(module, 'load_ros') as load:
            code = module.main(['--output', str(output), '--confirm-sitl',
                                '--candidate', 'candidate=' + '0' * 64,
                                '--controller-pid', '42', '--controller-binary-sha256', '0' * 64])
        self.assertEqual(code, 1)
        load.assert_not_called()
        self.assertIn('master unavailable', json.loads((output / 'summary.json').read_text())['error'])

    def test_candidate_hash_mismatch_stops_before_process_inspection(self):
        candidate = Path(self.tmp.name) / 'candidate'
        candidate.write_text('candidate bytes')
        args = NS(candidate=[str(candidate) + '=' + '0' * 64])
        with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
            module.runtime_preflight(args, None)

    def test_recorder_command_never_overwrites_and_honors_dimensions(self):
        args = NS(fps=8, video_size='1920x1080', display=':9')
        recorder = module.Recorder(Path(self.tmp.name), args)
        process = NS(poll=lambda: 0, returncode=0)
        with patch.object(module.subprocess, 'Popen', return_value=process) as popen:
            recorder.start()
        command = popen.call_args[0][0]
        self.assertIn('-n', command)
        self.assertNotIn('-y', command)
        self.assertEqual(command[command.index('-video_size') + 1], '1920x1080')
        self.assertEqual(command[command.index('-movflags') + 1], '+faststart')
        with self.assertRaisesRegex(RuntimeError, 'process exited'):
            recorder.check(require_frames=True)
        recorder.stderr.close()

    def test_record_only_never_imports_ros_or_checks_master(self):
        output = Path(self.tmp.name) / 'record-only'
        with patch.object(module, 'check_master', side_effect=AssertionError('ROS forbidden')), \
                patch.object(module, 'load_ros', side_effect=AssertionError('ROS forbidden')), \
                patch.object(module, 'recording_check', return_value={'passed': True}) as check:
            self.assertEqual(module.main(['--record-only', '--output', str(output)]), 0)
        self.assertTrue(check.call_args[0][1].record_only)

    def test_flight_identity_remains_required(self):
        with self.assertRaises(SystemExit) as error:
            module.main(['--output', str(Path(self.tmp.name) / 'missing-identity')])
        self.assertEqual(error.exception.code, 2)

    def test_recorder_ignores_incomplete_progress_block(self):
        root = Path(self.tmp.name)
        recorder = module.Recorder(root, NS(fps=10, video_size='2560x1494'))
        recorder.process = NS(poll=lambda: None, pid=99999999)
        recorder.started = module.time.monotonic() - 2
        (root / 'recorder.progress').write_text('frame=20\nprogress=continue\nframe=')
        self.assertEqual(recorder.check(require_frames=True)['frames'], 20)

    def test_callback_racing_close_is_safe(self):
        self.runner.connect()
        barrier = threading.Barrier(2)
        errors = []

        def callback():
            barrier.wait()
            try:
                for _ in range(100):
                    self.ros.refresh()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=callback)
        thread.start()
        barrier.wait()
        self.runner.close()
        thread.join()
        self.runner.message('ready', NS(data='bad json'))
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
