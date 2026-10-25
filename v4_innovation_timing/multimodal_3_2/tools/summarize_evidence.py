"""Recompute this rejected experiment's counts from the archived raw logs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import tarfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('archive', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    output = {'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest(),
              'scope': '4 implementation trials; no visual-model acceptance or hit-rate estimate',
              'trials': []}
    with tarfile.open(args.archive) as tar:
        manifest = json.load(tar.extractfile('MANIFEST.json'))
        for entry in manifest:
            raw = tar.extractfile(entry['path']).read()
            assert len(raw) == entry['bytes'], entry['path']
            assert hashlib.sha256(raw).hexdigest() == entry['sha256'], entry['path']
        output['manifest_entries_verified'] = len(manifest)
        trials = sorted({n.split('/')[1] for n in tar.getnames() if n.startswith('trials/')})
        for trial in trials:
            prefix = 'trials/' + trial + '/'
            observer = tar.extractfile(prefix + 'observer.out').read().decode('utf-8')
            start = observer.index('\n{') + 1
            result, _ = json.JSONDecoder().raw_decode(observer[start:])
            mission = tar.extractfile(prefix + 'mission_once.out').read().decode('utf-8', 'replace')
            events_name = next(n for n in tar.getnames()
                               if n.startswith(prefix + 'logs/') and n.endswith('.jsonl'))
            events = [json.loads(line) for line in tar.extractfile(events_name)]
            logs = [row for row in events if row.get('event') == 'rosout']
            messages = [(r['wall_time'], r.get('message', '')) for r in logs]
            decisions = [(stamp, msg) for stamp, msg in messages if msg.startswith('MULTIMODAL_DECISION')]
            latencies = [float(re.search(r'latency=([0-9.]+)s', m).group(1)) for _, m in decisions]
            boxes = sorted({re.search(r'bbox=(\[[^\]]+\])', msg).group(1) for _, msg in decisions})
            tracker_start = next((s for s,m in messages if m.startswith('[MultimodalTargetTracker] target=')), None)
            tracker_end = next((s for s,m in messages if m.startswith('[MultimodalTargetTracker]: Halted')), None)
            boundary_times = [s for s,m in messages if '[SafetyRecovery] ENTER' in m]
            scoped_boundary = [s for s in boundary_times if tracker_start and tracker_end
                               and tracker_start <= s <= tracker_end]
            sample = dict(trial=trial, total_time_s=float(result['total_time']),
                bt_success=result['bt_success'], observer_mission_success=result['mission_success'],
                observer_hit_balloon_status=result['hit_balloon_status'],
                independent_physical_hit_evidence='not collected',
                mission_eof_after_publish='请输入任务描述' in mission and '退出。' in mission,
                gate_start_count=sum(m.startswith('MULTIMODAL_GATE_START') for _,m in messages),
                window_ready_count=sum(m.startswith('MULTIMODAL_WINDOW_READY') for _,m in messages),
                decision_count=len(decisions), unique_boxes=boxes,
                decision_latency_min_s=min(latencies) if latencies else None,
                decision_latency_median_s=statistics.median(latencies) if latencies else None,
                decision_latency_max_s=max(latencies) if latencies else None,
                decision_latencies_s=latencies,
                tracker_start_utc=tracker_start, tracker_end_utc=tracker_end,
                boundary_event_times_utc=boundary_times,
                boundary_events_during_tracker=len(scoped_boundary),
                pixel_target_log_count=sum('model bbox -> pixel_target' in m for _,m in messages),
                control_log_count=sum(m.startswith('MULTIMODAL_CONTROL') for _,m in messages),
                core_dump_during_cleanup='dumped core' in mission)
            output['trials'].append(sample)
    data = json.dumps(output, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(data, encoding='utf-8')
    print(data, end='')


if __name__ == '__main__':
    main()
