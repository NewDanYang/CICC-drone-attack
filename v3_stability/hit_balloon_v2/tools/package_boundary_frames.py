#!/usr/bin/env python3
"""Archive real camera frames aligned to SafetyRecovery boundary entries.

Read-only evidence selector; it makes no collision inference.
Usage: python3 package_boundary_frames.py BATCH OUTPUT.tar.gz
"""

import csv
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import tarfile


def utc_seconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def add_json(archive, name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    batch, output = (Path(p) for p in sys.argv[1:])
    with (batch / 'trials.csv').open(newline='', encoding='utf-8') as source:
        trials = list(csv.DictReader(source))
    index = []
    with tarfile.open(output, 'w:gz') as archive:
        for trial in trials:
            path = Path(trial['trial_dir'])
            label = f"r{trial['round']}_{trial['color']}_a{trial['attempt']}"
            telemetry_files = list(path.glob('*telemetry.jsonl'))
            frame_index = path / 'real_frames/frames.jsonl'
            if len(telemetry_files) != 1 or not frame_index.is_file():
                index.append({'trial': label, 'error': 'missing telemetry or frame index'})
                continue
            events = [json.loads(line) for line in telemetry_files[0].read_text(encoding='utf-8').splitlines() if line.strip()]
            boundaries = [e for e in events if e.get('event') == 'rosout' and 'ENTER DRONE OUT OF BOUNDARY' in e.get('message', '')]
            frames = [json.loads(line) for line in frame_index.read_text(encoding='utf-8').splitlines() if line.strip()]
            for number, event in enumerate(boundaries, 1):
                moment = utc_seconds(event['wall_time'])
                nearest = min(range(len(frames)), key=lambda i: abs(utc_seconds(frames[i]['wall_time']) - moment))
                record = {'trial': label, 'event_number': number, 'event_time_utc': event['wall_time'], 'frames': []}
                for offset in (-1, 0, 1):
                    frame = frames[max(0, min(len(frames)-1, nearest+offset))]
                    file = path / 'real_frames' / frame['image']
                    if not file.is_file():
                        raise SystemExit(f'missing real frame: {file}')
                    name = f"{label}/event_{number:02d}/{frame['image']}"
                    archive.add(file, arcname=name)
                    record['frames'].append({'offset': offset, 'wall_time': frame['wall_time'], 'archive_path': name,
                                             'delta_seconds': round(utc_seconds(frame['wall_time']) - moment, 3)})
                index.append(record)
        add_json(archive, 'boundary_frame_index.json', index)
    print(f'{output} events={sum(1 for x in index if "event_number" in x)} bytes={output.stat().st_size}')


if __name__ == '__main__':
    main()
