#!/usr/bin/env python3
"""Agent-operated SITL protocol diagnostic; no model or manual-round credit."""
import argparse
import hashlib
import json
import math
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid
import xmlrpc.client
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse


FRESHNESS = {'state': 2.5, 'odom': 1.0, 'ready': 2.5}
TERMINAL = {'SUCCESS', 'FAILURE', 'ABORTED', 'TIMEOUT', 'REJECTED'}


def bounded_call(call, seconds=3):
    result = queue.Queue(maxsize=1)

    def invoke():
        try:
            result.put((True, call()))
        except BaseException as exc:
            result.put((False, exc))

    threading.Thread(target=invoke, daemon=True).start()
    try:
        ok, value = result.get(timeout=seconds)
    except queue.Empty:
        raise RuntimeError('call timed out; pending operation is unknown and must not be resent')
    if not ok:
        raise value
    return value


class TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = 2
        return connection


def local_rpc(uri, port=None):
    parsed = urlparse(uri)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or (port is not None and parsed.port != port) or parsed.username or parsed.password):
        raise RuntimeError('ROS endpoints must be loopback HTTP' + (' on port 11311' if port else ''))
    return xmlrpc.client.ServerProxy(uri, transport=TimeoutTransport())


def check_master():
    uri = os.environ.get('ROS_MASTER_URI', 'http://127.0.0.1:11311')
    master = local_rpc(uri, 11311)
    response = bounded_call(lambda: master.getPid('/sequential_diagnostic_preflight'))
    if response[0] != 1:
        raise RuntimeError('ROS master unavailable: ' + str(response))
    return master


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def runtime_preflight(args, master):
    candidates = {}
    for item in args.candidate:
        path, expected = item.rsplit('=', 1)
        actual = sha256(path)
        if len(expected) != 64 or actual != expected.lower():
            raise RuntimeError('candidate SHA256 mismatch: ' + path)
        candidates[str(Path(path).resolve())] = actual
    if not {'bt_ros.cpp', 'sequence_session.hpp', 'mission_once.py'}.issubset(
            {Path(path).name for path in candidates}):
        raise RuntimeError('exact candidate hashes required for controller source, session header and client')
    proc = Path('/proc')
    px4 = []
    for entry in proc.iterdir():
        if entry.name.isdigit():
            try:
                if (entry / 'comm').read_text().strip() == 'px4':
                    px4.append(int(entry.name))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    if not px4:
        raise RuntimeError('no local PX4 SITL process; --confirm-sitl alone is insufficient')
    response = bounded_call(lambda: master.lookupNode('/sequential_diagnostic_preflight', args.controller_node))
    if response[0] != 1:
        raise RuntimeError('controller node missing')
    node = local_rpc(response[2])
    pid_response = bounded_call(lambda: node.getPid('/sequential_diagnostic_preflight'))
    if pid_response[0] != 1 or pid_response[2] != args.controller_pid:
        raise RuntimeError('controller runtime PID mismatch')
    executable = proc / str(args.controller_pid) / 'exe'
    actual = sha256(executable)
    if actual != args.controller_binary_sha256.lower():
        raise RuntimeError('running controller binary SHA256 mismatch')
    return {'candidate_sha256': candidates, 'controller_pid': args.controller_pid,
            'controller_executable': str(executable.resolve()), 'controller_binary_sha256': actual,
            'px4_pids': px4}


class NoVideoRecorder:
    def __init__(self):
        self.proof = {'video_recorded': False, 'reason': 'explicitly skipped by operator'}

    def start(self):
        pass

    def check(self, require_frames=False):
        return self.proof

    def stop(self):
        pass


class Recorder:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.process = None
        self.stderr = None
        self.proof = {}
        self.progress_samples = []
        self.previous_progress = None
        self.frame_advanced = self.media_advanced = None

    def start(self):
        if shutil.disk_usage(self.root).free < 512 * 1024 * 1024:
            raise RuntimeError('less than 512 MiB free for recording')
        self.stderr = (self.root / 'recorder.log').open('x', encoding='utf-8')
        if getattr(self.args, 'media_self_test', False):
            capture = ['-re', '-f', 'lavfi', '-i',
                       'testsrc2=size=1280x748:rate=' + str(self.args.fps)]
        else:
            capture = ['-framerate', str(self.args.fps), '-video_size', self.args.video_size,
                       '-f', 'x11grab', '-i', self.args.display]
        environment = os.environ.copy()
        environment.setdefault('XAUTHORITY', '/home/ubuntu/.Xauthority')
        self.process = subprocess.Popen([
            'ffmpeg', '-n', '-loglevel', 'error',
            '-progress', str(self.root / 'recorder.progress'), *capture,
            '-vf', 'scale=1280:-2', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(self.root / 'outside.mp4')],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.stderr, env=environment)
        self.started = time.monotonic()

    def check(self, require_frames=False):
        if self.process.poll() is not None:
            detail = (self.root / 'recorder.log').read_text(encoding='utf-8', errors='replace')[-4000:]
            raise RuntimeError('recording process exited: ' + str(self.process.returncode) + '\n' + detail)
        progress = self.root / 'recorder.progress'
        values = {}
        if progress.exists():
            pending = {}
            for line in progress.read_text(encoding='utf-8').splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    pending[key] = value
                    if key == 'progress' and value in ('continue', 'end'):
                        values = pending
                        pending = {}
        frames = int(values.get('frame', '0').strip())
        media_us = values.get('out_time_us', values.get('out_time_ms'))
        if media_us is not None:
            media_seconds = int(media_us) / 1000000
        else:
            hours, minutes, seconds = values.get('out_time', '0:0:0').split(':')
            media_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if frames < 0 or not math.isfinite(media_seconds) or media_seconds < 0:
            raise RuntimeError('recording progress has invalid frame/media time')
        now = time.monotonic()
        elapsed = now - self.started
        if self.previous_progress is not None:
            previous_frames, previous_media = self.previous_progress
            if frames < previous_frames or media_seconds < previous_media:
                raise RuntimeError('recording frame/media time regressed')
            if frames > previous_frames:
                self.frame_advanced = max(now, self.started + 2)
            if media_seconds > previous_media:
                self.media_advanced = max(now, self.started + 2)
        else:
            self.frame_advanced = self.media_advanced = max(now, self.started + 2)
        self.previous_progress = (frames, media_seconds)
        rolling_fps = rolling_media_rate = None
        if elapsed >= 2:
            self.progress_samples.append((now, frames, media_seconds))
            while len(self.progress_samples) > 1 and now - self.progress_samples[1][0] >= 3:
                self.progress_samples.pop(0)
            window_start, start_frames, start_media = self.progress_samples[0]
            window = now - window_start
            if window >= 3:
                rolling_fps = (frames - start_frames) / window
                rolling_media_rate = (media_seconds - start_media) / window
            if now - self.frame_advanced >= 3 or now - self.media_advanced >= 3:
                raise RuntimeError('recording frame/media time stopped advancing')
            if rolling_fps is not None and (rolling_fps < self.args.fps * .5 or rolling_media_rate < .5):
                raise RuntimeError('recording sustained frame/media cadence below half requested rate')
        self.proof = {'pid': self.process.pid, 'frames': frames, 'elapsed_seconds': elapsed,
                      'observed_fps': frames / max(elapsed, .001),
                      'media_seconds': media_seconds, 'rolling_fps': rolling_fps,
                      'rolling_media_rate': rolling_media_rate,
                      'requested_fps': self.args.fps, 'video_size': self.args.video_size,
                      'free_bytes': shutil.disk_usage(self.root).free,
                      'load_average': list(os.getloadavg()) if hasattr(os, 'getloadavg') else None}
        stat = Path('/proc') / str(self.process.pid) / 'status'
        if stat.exists():
            self.proof['process_status'] = stat.read_text()
        if require_frames and (frames < 2 or self.proof['observed_fps'] < self.args.fps * .5):
            raise RuntimeError('recording has insufficient frame/fps evidence before takeoff')
        if elapsed > 3 and (not progress.exists() or time.time() - progress.stat().st_mtime > 3):
            raise RuntimeError('recording progress stopped')
        return self.proof

    def stop(self):
        try:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.communicate(b'q', timeout=12)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            if self.process is not None and self.process.returncode != 0:
                raise RuntimeError('recorder failed to finalize MP4')
            if self.process is not None:
                result = subprocess.run(['ffprobe', '-v', 'error', '-read_intervals', '0%+5',
                                         '-count_frames', '-select_streams', 'v:0',
                                         '-show_entries', 'stream=width,height,avg_frame_rate,nb_read_frames:format=duration',
                                         '-of', 'json', str(self.root / 'outside.mp4')],
                                        capture_output=True, text=True, timeout=5, check=True)
                self.proof['final_media'] = json.loads(result.stdout)
                streams = self.proof['final_media'].get('streams', [])
                if not streams or int(streams[0].get('nb_read_frames', 0)) < 2:
                    raise RuntimeError('final MP4 has no decodable frame evidence')
                duration = float(self.proof['final_media'].get('format', {}).get('duration', 0))
                if not math.isfinite(duration) or duration <= 0:
                    raise RuntimeError('final MP4 has invalid duration')
                decode_timeout = min(120, max(15, duration * .5))
                decoded = subprocess.run([
                    'ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(self.root / 'outside.mp4'),
                    '-map', '0:v:0', '-f', 'null', os.devnull],
                    capture_output=True, text=True, timeout=decode_timeout, check=True)
                if decoded.stderr.strip():
                    raise RuntimeError('final MP4 full-file decode failed: ' + decoded.stderr[-4000:])
                self.proof['full_file_decode'] = {'passed': True, 'timeout_seconds': decode_timeout}
        finally:
            if self.stderr:
                self.stderr.close()


class Diagnostic:
    def __init__(self, root, ros, recorder, clock=time.monotonic, sleep=time.sleep):
        self.root, self.ros, self.recorder = Path(root), ros, recorder
        self.clock, self.sleep = clock, sleep
        self.lock = threading.RLock()
        self.closed = False
        self.interrupted = False
        self.log = (self.root / 'events.jsonl').open('x', encoding='utf-8')
        self.samples, self.outcomes, self.subscribers = {}, {}, []
        self.epoch = None
        self.session = uuid.uuid4().hex
        self.active = None
        self.accepted = False
        self.report = {'scope': __doc__, 'passed': False, 'model_used': False,
                       'manual_round_credit': False, 'retry_allowed': False}

    def event(self, kind, value):
        with self.lock:
            if not self.closed:
                self.log.write(json.dumps({'utc': time.time(), 'monotonic': self.clock(),
                                           'event': kind, 'value': value}) + '\n')
                self.log.flush()

    def telemetry(self, kind, msg):
        with self.lock:
            if self.closed:
                return
            stamp = msg.header.stamp.to_sec()
            now_source = self.ros.now()
            previous = self.samples.get(kind)
            if (not math.isfinite(stamp) or stamp <= 0 or now_source - stamp > FRESHNESS[kind]
                    or stamp - now_source > .1 or (previous and stamp <= previous['source_stamp'])):
                self.event('ignored_telemetry', {'kind': kind, 'source_stamp': stamp})
                return
            if kind == 'odom':
                p = msg.pose.pose.position
                fields = [p.x, p.y, p.z]
                if not all(math.isfinite(v) for v in fields):
                    self.event('invalid_telemetry', kind)
                    return
            self.samples[kind] = {'message': msg, 'receipt': self.clock(), 'source_stamp': stamp}
            self.event(kind, {'source_stamp': stamp, 'receipt': self.clock(),
                              'position': fields} if kind == 'odom' else
                       {'source_stamp': stamp, 'receipt': self.clock(), 'armed': msg.armed,
                        'connected': msg.connected, 'mode': msg.mode})

    def message(self, kind, msg):
        with self.lock:
            if self.closed:
                return
            try:
                value = json.loads(msg.data)
                if not isinstance(value, dict) or value.get('protocol') != 1:
                    raise ValueError('invalid protocol object')
            except (ValueError, TypeError) as exc:
                self.event('invalid_message', str(exc))
                return
            if kind == 'ready':
                if self.epoch and value.get('server_epoch') != self.epoch:
                    self.event('epoch_changed', value)
                    self.report['epoch_changed'] = True
                    return
                self.samples['ready'] = {'message': value, 'receipt': self.clock()}
            elif (self.active and value.get('server_epoch') == self.epoch
                  and value.get('session_id') == self.session
                  and value.get('request_id') == self.active['request_id']
                  and value.get('command') == self.active['command']):
                if value.get('status') == 'ACCEPTED':
                    self.accepted = True
                self.outcomes.setdefault(self.active['request_id'], []).append(value)
            else:
                self.event('ignored_status', value)
                return
            self.event(kind, value)

    def connect(self):
        self.subscribers = []
        for topic, msg_type, callback in (
                ('/mavros/state', self.ros.State, lambda m: self.telemetry('state', m)),
                ('/rflysim/uav1/local/odom', self.ros.Odometry, lambda m: self.telemetry('odom', m)),
                ('/mission_ready', self.ros.String, lambda m: self.message('ready', m)),
                ('/mission_status', self.ros.String, lambda m: self.message('status', m))):
            self.subscribers.append(self.ros.Subscriber(topic, msg_type, callback))
        self.pub = self.ros.Publisher('/mission_request', self.ros.String, queue_size=1)
        self.abort = self.ros.Publisher('/mission_abort', self.ros.String, queue_size=1)

    def fresh(self, kind):
        with self.lock:
            sample = self.samples.get(kind)
            if sample is None or self.clock() - sample['receipt'] > FRESHNESS[kind]:
                return False
            if kind != 'ready':
                age = self.ros.now() - sample['source_stamp']
                if age > FRESHNESS[kind] or age < -.1:
                    return False
            return True

    def wait(self, predicate, seconds, interruptible=True):
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            if interruptible and self.interrupted:
                raise RuntimeError('diagnostic interrupted; recovery required')
            if self.ros.is_shutdown():
                raise RuntimeError('ROS shutdown')
            value = predicate()
            if value:
                return value
            self.sleep(.05)
        raise RuntimeError('bounded wait expired')

    def guard(self):
        if self.interrupted:
            raise RuntimeError('diagnostic interrupted; recovery required')
        with self.lock:
            if not all(self.fresh(k) for k in ('state', 'odom', 'ready')):
                raise RuntimeError('diagnostic telemetry stale (receipt or source)')
            if self.report.get('epoch_changed'):
                raise RuntimeError('controller epoch changed; active identity retained')
            state = self.samples['state']['message']
            p = self.samples['odom']['message'].pose.pose.position
            if not state.connected:
                raise RuntimeError('flight controller disconnected')
            if not all(math.isfinite(v) for v in (p.x, p.y, p.z)) or abs(p.x) > .65 or abs(p.y) > .65 or not -.25 <= p.z <= 1.5:
                raise RuntimeError('diagnostic position guard triggered')
        self.recorder.check()

    def request(self, command='', reset=False, timeout=45):
        self.guard()
        with self.lock:
            if self.active:
                raise RuntimeError('previous request unresolved; no resend allowed')
            ident = uuid.uuid4().hex
            self.active = {'request_id': ident, 'command': command}
            self.accepted = False
        payload = {'protocol': 1, 'server_epoch': self.epoch, 'session_id': self.session,
                   'request_id': ident}
        payload.update({'reset': True} if reset else {'command': command})
        self.event('send', payload)
        self.pub.publish(self.ros.String(data=json.dumps(payload)))
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            self.guard()
            with self.lock:
                messages = self.outcomes.pop(ident, [])
                for row in messages:
                    if row.get('status') == 'ACCEPTED':
                        self.accepted = True
                    if row.get('status') in TERMINAL:
                        self.event('terminal', row)
                        self.active = None
                        self.accepted = False
                        if row['status'] != 'SUCCESS':
                            raise RuntimeError('command failed: ' + json.dumps(row))
                        return row
            if self.ros.is_shutdown():
                raise RuntimeError('ROS shutdown with active identity retained')
            self.sleep(.05)
        raise RuntimeError('command timeout; active identity retained; no automatic resend')

    def recovery(self, reason):
        self.event('recovery', reason)
        with self.lock:
            active = dict(self.active) if self.active else None
            accepted = self.accepted
            armed = self.fresh('state') and self.samples['state']['message'].armed
        self.report['unresolved_request'] = active
        if not accepted and not armed:
            self.event('recovery_skipped', 'no accepted active request or fresh armed telemetry')
            return
        if active and accepted:
            payload = {'protocol': 1, 'server_epoch': self.epoch, 'session_id': self.session,
                       'request_id': active['request_id']}
            self.abort.publish(self.ros.String(data=json.dumps(payload)))
            self.event('abort_sent', payload)
        if armed:
            try:
                result = bounded_call(self.ros.land, 3)
                self.event('recovery_mode_request', {'mode_sent': result.mode_sent})
            except Exception as exc:
                self.event('recovery_mode_error', str(exc))
        try:
            self.wait(lambda: self.fresh('state') and self.fresh('odom')
                      and not self.samples['state']['message'].armed, 35, interruptible=False)
            self.report['recovery_disarmed_fresh'] = True
        except Exception as exc:
            self.report['recovery_error'] = str(exc)

    def close(self):
        for subscriber in self.subscribers:
            try:
                subscriber.unregister()
            except Exception as exc:
                self.event('unsubscribe_error', str(exc))
        with self.lock:
            self.closed = True
            self.log.close()

    def run(self, preflight):
        previous_signals = {}
        if threading.current_thread() is threading.main_thread():
            def interrupt(signum, frame):
                self.interrupted = True
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_signals[signum] = signal.signal(signum, interrupt)
        try:
            self.report['preflight_identity'] = preflight()
            self.event('preflight_identity', self.report['preflight_identity'])
            bounded_call(lambda: self.ros.init_node('sequential_live_diagnostic', anonymous=True,
                                                   disable_signals=True), 5)
            if self.interrupted:
                raise RuntimeError('diagnostic interrupted during initialization')
            self.connect()
            self.wait(lambda: all(self.fresh(k) for k in ('state', 'odom', 'ready'))
                      and self.pub.get_num_connections(), 12)
            state = self.samples['state']['message']
            ready = self.samples['ready']['message']
            p = self.samples['odom']['message'].pose.pose.position
            if state.armed or not state.connected or ready.get('state') != 'IDLE':
                raise RuntimeError('must begin connected, disarmed, IDLE')
            if abs(p.x) > .3 or abs(p.y) > .3 or abs(p.z) > .25:
                raise RuntimeError('not at diagnostic start position')
            self.epoch = ready.get('server_epoch')
            if not isinstance(self.epoch, str) or not self.epoch:
                raise RuntimeError('missing server epoch')
            self.recorder.start()
            self.sleep(2)
            self.report['recorder_preflight'] = self.recorder.check(require_frames=True)
            self.request(reset=True, timeout=10)
            self.request('takeoff', timeout=40)
            deadline = self.clock() + 5
            while self.clock() < deadline:
                self.guard()
                state = self.samples['state']['message']
                p = self.samples['odom']['message'].pose.pose.position
                if not state.armed or state.mode != 'OFFBOARD' or abs(p.z - 1) > .25:
                    raise RuntimeError('hover not supported by fresh live telemetry')
                self.sleep(.05)
            self.event('hover_verified', {'seconds': 5, 'z': p.z})
            self.request('land', timeout=50)
            self.wait(lambda: self.fresh('state') and self.fresh('odom')
                      and not self.samples['state']['message'].armed, 10)
            p = self.samples['odom']['message'].pose.pose.position
            if abs(p.z) > .25:
                raise RuntimeError('landing height not supported by fresh telemetry')
            self.report.update(passed=True, final_position=[p.x, p.y, p.z])
        except Exception as exc:
            self.report['error'] = repr(exc)
            try:
                self.recovery(str(exc))
            except Exception as recovery_error:
                self.report['recovery_error'] = repr(recovery_error)
        finally:
            try:
                self.recorder.stop()
            except Exception as exc:
                self.report.update(passed=False, recorder_error=repr(exc))
            self.report['recorder_final'] = self.recorder.proof
            self.report['final_armed'] = (self.samples['state']['message'].armed
                                          if self.fresh('state') else None)
            self.event('summary', self.report)
            try:
                self.close()
                (self.root / 'summary.json').write_text(json.dumps(self.report, indent=2) + '\n', encoding='utf-8')
            finally:
                for signum, previous in previous_signals.items():
                    signal.signal(signum, previous)
        return self.report


def load_ros():
    import rospy
    from mavros_msgs.msg import State
    from mavros_msgs.srv import SetMode, SetModeRequest
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String
    return SimpleNamespace(State=State, Odometry=Odometry, String=String,
                           Subscriber=rospy.Subscriber, Publisher=rospy.Publisher,
                           init_node=rospy.init_node, is_shutdown=rospy.is_shutdown,
                           now=lambda: rospy.Time.now().to_sec(),
                           land=lambda: rospy.ServiceProxy('/mavros/set_mode', SetMode)(
                               SetModeRequest(custom_mode='AUTO.LAND')))


def recording_check(root, args):
    recorder = Recorder(root, args)
    report = {'passed': False, 'flight_commands_sent': False,
              'scope': 'synthetic media compatibility only' if args.media_self_test else 'desktop recording only'}
    try:
        recorder.start()
        deadline = time.monotonic() + args.record_seconds
        while time.monotonic() < deadline:
            time.sleep(.25)
            recorder.check()
        recorder.check(require_frames=True)
        report['passed'] = True
    except Exception as exc:
        report['error'] = repr(exc)
    finally:
        try:
            recorder.stop()
        except Exception as exc:
            report.update(passed=False, recorder_error=repr(exc))
        report['recording'] = recorder.proof
        (root / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--record-only', action='store_true', help='record desktop without importing ROS or issuing flight commands')
    mode.add_argument('--media-self-test', action='store_true', help='test encoder with synthetic frames; no desktop or ROS required')
    parser.add_argument('--record-seconds', type=float, default=6)
    parser.add_argument('--output', required=True)
    parser.add_argument('--confirm-sitl', action='store_true')
    parser.add_argument('--candidate', action='append', metavar='PATH=SHA256')
    parser.add_argument('--controller-pid', type=int)
    parser.add_argument('--controller-node', default='/llm_mission_node')
    parser.add_argument('--controller-binary-sha256')
    parser.add_argument('--display', default=':20')
    parser.add_argument('--video-size', default='2560x1494')
    parser.add_argument('--fps', type=int, default=10)
    parser.add_argument('--skip-video', action='store_true', help='run with telemetry evidence only; no visual collision claims')
    args = parser.parse_args(argv)
    if args.fps <= 0 or len(args.video_size.split('x')) != 2 or not all(
            part.isdigit() and int(part) > 0 for part in args.video_size.split('x')):
        parser.error('invalid recording dimensions or fps')
    recording_only = args.record_only or args.media_self_test
    if recording_only and (args.skip_video or not math.isfinite(args.record_seconds)
                           or not 2 <= args.record_seconds <= 3600):
        parser.error('recording requires video and a duration between 2 and 3600 seconds')
    if not recording_only and not all((args.confirm_sitl, args.candidate,
                                       args.controller_pid, args.controller_binary_sha256)):
        parser.error('flight diagnostic requires --confirm-sitl, --candidate, --controller-pid and --controller-binary-sha256')
    root = Path(args.output)
    root.mkdir(exist_ok=False, parents=False)
    if recording_only:
        report = recording_check(root, args)
        print(json.dumps(report, indent=2), flush=True)
        return 0 if report['passed'] else 1
    # ROS imports and init happen only after the bounded master/identity checks.
    runner = Diagnostic(root, None, NoVideoRecorder() if args.skip_video else Recorder(root, args))

    def preflight():
        if args.fps <= 0 or len(args.video_size.split('x')) != 2 or not all(
                part.isdigit() and int(part) > 0 for part in args.video_size.split('x')):
            raise RuntimeError('invalid recording dimensions or fps')
        master = check_master()
        identity = runtime_preflight(args, master)
        runner.ros = load_ros()
        return identity

    report = runner.run(preflight)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
