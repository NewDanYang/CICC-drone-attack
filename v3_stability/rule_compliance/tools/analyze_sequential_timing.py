#!/usr/bin/env python3
"""Offline evidence-only sequential timing. No ROS installation or instance required."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

ANSI = re.compile(r'\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]')
ROOT = re.compile(r'^\[(\d+(?:\.\d+)?)\]:\s+LLMSequence\s+(\w+)\s+->\s+(\w+)')
TERMINAL = {'SUCCESS', 'FAILURE'}
ORDER = ['takeoff', 'cross_frame', 'detect_aruco', 'return_cross_frame', 'hit_balloon', 'land']


def seconds(a, b):
    return float(Decimal(str(b)) - Decimal(str(a)))


def model_evidence(text):
    requests = {}
    retries = []
    warnings = []
    for number, line in enumerate(ANSI.sub('', text).splitlines(), 1):
        if re.search(r'\[命令校验\].*第\d+次生成不合格', line):
            retries.append({'line': number, 'text': line.strip()})
        match = re.search(r'\[(SEND|STATUS|RESULT)\]\s*(\{.*)', line)
        if not match:
            continue
        try:
            data = json.loads(match[2])
        except json.JSONDecodeError:
            warnings.append('malformed model JSON at line {}'.format(number))
            continue
        if not data.get('command') or not data.get('request_id'):
            continue
        key = (data.get('server_epoch'), data.get('session_id'), data['request_id'])
        request = requests.setdefault(key, {
            'command': data['command'], 'request_id': data['request_id'],
            'epoch': data.get('server_epoch'), 'accepted': False,
            'status': None, 'reason': '', 'line': number})
        if data.get('status') == 'ACCEPTED':
            request['accepted'] = True
        if data.get('status') in {'SUCCESS', 'FAILURE', 'ABORTED', 'REJECTED'}:
            request.update(status=data['status'], reason=data.get('reason', ''))
    return list(requests.values()), retries, warnings


def infer_command(body):
    if '[Takeoff]' in body or re.search(r':\s+Takeoff\s+', body):
        return 'takeoff'
    if '[Land]' in body or re.search(r':\s+Land\s+', body):
        return 'land'
    if 'TargetTracker' in body or 'VisualServo' in body:
        color = re.search(r'(red|purple|blue)_balloon', body)
        return 'hit_balloon' + (':' + color[1] if color else '')
    if 'ArucoDetector' in body:
        return 'detect_aruco'
    if 'frame: 1' in body:
        return 'return_cross_frame'
    if 'TargetLocator' in body and 'square_frame' in body:
        return 'cross_frame'
    return None


def analyze(mission_text, model_text=''):
    lines = ANSI.sub('', mission_text).splitlines()
    stages = []
    active = None
    epoch = None
    segment = 0
    last_root_time = None
    warnings = []
    for number, line in enumerate(lines, 1):
        if 'Behavior Tree Mission Node Started' in line or 'Sequential protocol ready' in line:
            if active is not None:
                active = None
                warnings.append('controller restart interrupted command at line {}'.format(number))
            segment += 1
            last_root_time = None
            match = re.search(r'epoch=(\w+)', line)
            epoch = match[1] if match else None
        match = ROOT.match(line)
        if not match:
            continue
        stamp, old, new = match.groups()
        if last_root_time is not None and Decimal(stamp) < Decimal(last_root_time):
            segment += 1
            active = None
            warnings.append('BT clock moved backward at line {}'.format(number))
        last_root_time = stamp
        if new == 'RUNNING' and old != 'RUNNING':
            if active is not None:
                warnings.append('new command before terminal at line {}'.format(number))
            active = {'start_timestamp': stamp, 'terminal_timestamp': None,
                      'start_line': number, 'terminal_line': None,
                      'segment': segment, 'epoch': epoch, 'bt_outcome': 'INCOMPLETE'}
            stages.append(active)
        elif old == 'RUNNING' and new in TERMINAL:
            if active is None:
                warnings.append('terminal without matching start at line {}'.format(number))
            else:
                active.update(terminal_timestamp=stamp, terminal_line=number, bt_outcome=new)
                active = None
    requests, retries, model_warnings = model_evidence(model_text)
    warnings.extend(model_warnings)
    accepted = [r for r in requests if r['accepted']]
    for i, stage in enumerate(stages):
        end = stage['terminal_line'] or (stages[i + 1]['start_line'] - 1 if i + 1 < len(stages) else len(lines))
        stage['command'] = infer_command('\n'.join(lines[stage['start_line'] - 1:end]))
        stage['execution_s'] = (seconds(stage['start_timestamp'], stage['terminal_timestamp'])
                                if stage['terminal_timestamp'] is not None else None)
        stage['model_outcome'] = None
        stage['outcome'] = stage['bt_outcome']
        if stage['command'] and stage['command'].startswith('hit_balloon') and stage['bt_outcome'] == 'SUCCESS':
            stage['outcome'] = 'ATTEMPTED_UNVERIFIED'
    # Untimestamped statuses are only correlated when the entire accepted sequence agrees.
    aligned = bool(stages) and len(accepted) == len(stages) and all(
        s['command'] == r['command'] and s['epoch'] == r['epoch']
        for s, r in zip(stages, accepted))
    if aligned:
        for stage, request in zip(stages, accepted):
            stage['model_outcome'] = request['status']
            stage['model_reason'] = request['reason']
            stage['request_id'] = request['request_id']
            if request['status'] and request['status'] != stage['bt_outcome']:
                warnings.append('model/controller outcome mismatch for ' + str(stage['command']))
    elif requests:
        warnings.append('model statuses not correlated: count, epoch or controller stage evidence differs')
    gaps = []
    for previous, following in zip(stages, stages[1:]):
        valid = (previous['segment'] == following['segment'] and previous['terminal_timestamp'] is not None)
        duration = seconds(previous['terminal_timestamp'], following['start_timestamp']) if valid else None
        gaps.append({'after': previous['command'], 'before': following['command'],
                     'idle_s': duration if duration is not None and duration >= 0 else None,
                     'terminal_line': previous['terminal_line'], 'next_start_line': following['start_line']})
    takeoffs = [s for s in stages if s['command'] == 'takeoff']
    lands = [s for s in stages if s['command'] == 'land']
    elapsed = None
    if takeoffs and lands:
        first, final = takeoffs[0], lands[-1]
        if (first['segment'] == final['segment'] and final['bt_outcome'] == 'SUCCESS'
                and Decimal(final['terminal_timestamp']) >= Decimal(first['start_timestamp'])):
            elapsed = seconds(first['start_timestamp'], final['terminal_timestamp'])
    sequence = [s['command'].split(':')[0] if s['command'] else None for s in stages]
    complete = (sequence == ORDER and len({s['segment'] for s in stages}) == 1
                and all(s['bt_outcome'] == 'SUCCESS' for s in stages))
    execution = [s['execution_s'] for s in stages if s['execution_s'] is not None]
    idle = [g['idle_s'] for g in gaps if g['idle_s'] is not None]
    return {'schema_version': 1, 'timing_source': 'controller LLMSequence BT timestamps (seconds, millisecond precision)',
            'model_timestamps_available': False, 'model_statuses_correlated': aligned,
            'model_validation_retry_count': len(retries), 'model_validation_retries': retries,
            'model_requests': requests, 'stages': stages, 'idle_gaps': gaps,
            'summary': {'controller_sequence_complete': complete,
                        'observed_execution_s': round(sum(execution), 6),
                        'observed_idle_s': round(sum(idle), 6),
                        'unmeasured_execution_count': len(stages) - len(execution),
                        'unmeasured_idle_count': len(gaps) - len(idle),
                        'takeoff_start_to_final_land_s': elapsed,
                        'airborne_time_s': None,
                        'airborne_time_reason': 'unknown: no timestamped landed-state telemetry analyzed; command span is not airborne time'},
            'warnings': warnings,
            'limitations': ['Idle includes human confirmation, model generation, validation and transport; those components cannot be separated without timestamps.',
                            'Video duration is not flight time. Balloon BT success is ATTEMPTED_UNVERIFIED, not evidence of a burst.',
                            'Missing starts/terminals and restart or clock-reset boundaries are never interpolated.']}


def bag_evidence(path, topic='/mavros/extended_state'):
    result = {'path': str(path), 'topic': topic, 'airborne_time_s': None}
    if not path.exists():
        return dict(result, reason='bag file missing')
    try:
        from rosbags.highlevel import AnyReader
    except ImportError:
        return dict(result, reason='rosbags not installed; bag telemetry not analyzed')
    try:
        with AnyReader([path]) as reader:
            connections = [c for c in reader.connections if c.topic == topic]
            transitions = []
            for connection, timestamp, raw in reader.messages(connections=connections):
                msg = reader.deserialize(raw, connection.msgtype)
                state = getattr(msg, 'landed_state', None)
                if state not in (1, 2):
                    continue
                if not transitions or state != transitions[-1][1]:
                    transitions.append((timestamp, state))
            result['landed_state_transitions'] = transitions
            # Both ground boundaries must be observed; a bag clipped in flight is insufficient.
            if len(transitions) == 3 and [s for _, s in transitions] == [1, 2, 1]:
                result['airborne_time_s'] = (transitions[2][0] - transitions[1][0]) / 1e9
                result['reason'] = 'sampled landed_state IN_AIR to ON_GROUND using bag record timestamps'
            else:
                result['reason'] = 'unknown: missing or ambiguous ground/air/ground telemetry boundaries'
    except Exception as exc:
        result['reason'] = 'bag unreadable: {}: {}'.format(type(exc).__name__, exc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mission-log', required=True, type=Path)
    parser.add_argument('--model-log', type=Path)
    parser.add_argument('--bag', type=Path)
    parser.add_argument('--landed-state-topic', default='/mavros/extended_state')
    parser.add_argument('-o', '--output', type=Path, help='JSON file; default stdout')
    args = parser.parse_args(argv)
    try:
        report = analyze(args.mission_log.read_text(encoding='utf-8', errors='replace'),
                         args.model_log.read_text(encoding='utf-8', errors='replace') if args.model_log else '')
        report['sources'] = {'mission_log': str(args.mission_log),
                             'model_log': str(args.model_log) if args.model_log else None}
        if args.bag:
            report['bag'] = bag_evidence(args.bag, args.landed_state_topic)
            report['summary']['airborne_time_s'] = report['bag']['airborne_time_s']
            report['summary']['airborne_time_reason'] = report['bag']['reason']
        payload = json.dumps(report, ensure_ascii=True, indent=2) + '\n'
        if args.output:
            args.output.write_text(payload, encoding='utf-8')
        else:
            print(payload, end='')
    except OSError as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
