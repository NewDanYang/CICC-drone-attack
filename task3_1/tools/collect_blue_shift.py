"""Collect simulated camera frames at a documented temporary camera offset."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import time

SDK = Path('/home/ubuntu/PX4PSP/RflySimAPIs/RflySimSDK')
for part in ('', 'comm', 'ctrl', 'ue', 'vision', 'phm', 'swarm', 'adb', 'wsl', 'test', 'word'):
    sys.path.insert(0, str(SDK / part))

import rospy
from sensor_msgs.msg import Image
from PIL import Image as PILImage, ImageDraw
import VisionCaptureApi


def main():
    rospy.init_node('collect_camera_shift_diagnostic', anonymous=True)
    config = Path('/home/ubuntu/catkin_ws/src/sensor_pkg/Config.json')
    vis = VisionCaptureApi.VisionCaptureApi('127.0.0.1')
    vis.jsonLoad(1)
    original = copy.deepcopy(next(s for s in vis.VisSensor if s.SeqID == 1))
    view = copy.deepcopy(original)
    view.SensorPosXYZ = [3.5, 0, -1.0]
    out = Path('/home/ubuntu/multimodal_task3') / (
        'blue_shift_diagnostic_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    out.mkdir(parents=True, exist_ok=False)
    meta = {
        'scope': 'Simulation diagnostic with changed camera extrinsics; separate from original fixed-camera evaluation.',
        'selection': '20 scheduled frames, 1 second apart; no model or color gating; all retained.',
        'labels': 'Unreviewed; expected blue scene is not independent ground truth.',
        'original_position': list(original.SensorPosXYZ),
        'temporary_position': list(view.SensorPosXYZ),
        'angles': list(view.SensorAngEular),
        'topic': '/rflysim/sensor1/img_rgb',
        'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
        'restoration': 'not yet requested',
    }
    def save_meta():
        (out / 'capture.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    save_meta()
    frames = []
    try:
        for _ in range(3):
            vis.sendUpdateUEImage(view, 0, '127.0.0.1')
            time.sleep(0.2)
        time.sleep(2)
        with (out / 'manifest.jsonl').open('w', encoding='utf-8') as stream:
            previous_header = None
            for index in range(20):
                if index:
                    time.sleep(1)
                msg = rospy.wait_for_message(meta['topic'], Image, timeout=10)
                header = [msg.header.stamp.secs, msg.header.stamp.nsecs, msg.header.seq]
                if previous_header == header:
                    raise RuntimeError('Repeated image header; stopping collection')
                previous_header = header
                if msg.encoding != 'bgr8':
                    raise RuntimeError('Unexpected encoding: ' + msg.encoding)
                im = PILImage.frombytes('RGB', (msg.width, msg.height), bytes(msg.data),
                                       'raw', 'BGR', msg.step, 1)
                path = out / ('frame_%03d.png' % index)
                im.save(path)
                frames.append(path)
                row = {'image': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'header': header, 'received_utc': datetime.now(timezone.utc).isoformat(),
                       'width': msg.width, 'height': msg.height, 'label_status': 'unreviewed'}
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                im.close()
                print('Saved %d/20: %s' % (index + 1, path.name), flush=True)
    finally:
        try:
            for _ in range(3):
                vis.sendUpdateUEImage(original, 0, '127.0.0.1')
                time.sleep(0.2)
            meta['restoration'] = 'Original camera restore requests sent; not independently verified.'
        except Exception as exc:
            meta['restoration'] = 'Restore request failed: ' + repr(exc)
        meta['saved_frames'] = len(frames)
        save_meta()
        print(meta['restoration'], flush=True)
        print('Data directory:', out, flush=True)
    grid = PILImage.new('RGB', (320 * 5, 264 * 4), 'white')
    draw = ImageDraw.Draw(grid)
    for index, path in enumerate(frames):
        with PILImage.open(path) as im:
            thumb = im.resize((320, 240))
        x, y = index % 5 * 320, index // 5 * 264
        grid.paste(thumb, (x, y))
        draw.text((x + 5, y + 243), path.name, fill='black')
    grid.save(out / 'contact_sheet.jpg', quality=92)
    grid.save('/tmp/task3_blue_shift_contact.jpg', quality=92)
    archive = Path('/tmp/task3_blue_shift_review.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(out, arcname=out.name)
    print('COLLECT_OK: 20 frames; preview /tmp/task3_blue_shift_contact.jpg', flush=True)
    print('Review archive:', archive, flush=True)


if __name__ == '__main__':
    main()
