#!/usr/bin/env python3
"""No-flight check of command generation (greedy decoding).  Publishes nothing.

Imports load_model / generate_validated_commands from a mission_once.py file
(patched or original) without running its main(), then asks each task phrasing
--repeats times.  With greedy decoding a phrasing is either always right or
always wrong, so the useful axis is phrasing variety, not repeats; the official
five instruction sets are only published 2 h before the match, so run this on
them on the day as well.

  /opt/conda/envs/demo/bin/python3 command_check.py --mission /home/ubuntu/model/mission_once.py \
      --out /root/gpufree-data/fm9g_v8/command_check_$(date +%Y%m%dT%H%M%S).json
"""
import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

TASKS = [
    ('red', '起飞，穿过框，识别二维码，再穿回来，去A区打红色气球，降落'),
    ('red', '无人机起飞，穿越方框，识别地面二维码，逆序穿越方框，扎破红色气球，返航降落'),
    ('purple', '请起飞后穿越方框障碍，然后识别地面上的二维码，再反向穿越方框，接着扎破紫色气球，最后返航降落。'),
    ('blue', '起飞；穿越方框；识别二维码；返回穿越方框；击破蓝色气球；返回起点并降落'),
    ('blue', '先让无人机起飞，穿过前面的方框，到二维码上方识别它，然后从方框穿回来，去打掉蓝色的气球，最后降落'),
]


def expected(color):
    return ['takeoff', 'cross_frame', 'detect_aruco', 'return_cross_frame', 'hit_balloon:' + color, 'land']


def parse(commands):
    return [l.strip() for l in (commands or '').splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mission', default='/home/ubuntu/model/mission_once.py', type=Path)
    ap.add_argument('--repeats', type=int, default=2)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location('mission_once_under_test', a.mission)
    mo = importlib.util.module_from_spec(spec)
    sys.argv = [str(a.mission)]
    spec.loader.exec_module(mo)          # defines functions only; main() is not called
    src = a.mission.read_text(encoding='utf-8-sig')
    greedy = len(re.findall(r'sampling=False', src)) >= 2
    t0 = time.monotonic()
    model, tok, base = mo.load_model()
    load_s = time.monotonic() - t0
    generate = getattr(mo, 'generate_validated_commands', None) or mo.generate_commands
    rows = []
    for color, task in TASKS:
        for i in range(a.repeats):
            s = time.monotonic()
            cmds = generate(model, tok, base, task)
            got = parse(cmds)
            rows.append({'task': task, 'repeat': i, 'ok': got == expected(color), 'commands': got,
                         'latency_s': time.monotonic() - s})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    result = {'mission': str(a.mission), 'greedy': greedy, 'generator': generate.__name__, 'init_reply': base[-1]['content'][0][:300],
              'load_s': load_s, 'passed': sum(r['ok'] for r in rows), 'total': len(rows), 'rows': rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print('PASSED %d/%d greedy=%s' % (result['passed'], result['total'], greedy))


if __name__ == '__main__':
    main()
