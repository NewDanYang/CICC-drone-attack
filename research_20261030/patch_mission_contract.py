"""Patch an isolated copy of mission_once.py. Refuse unknown layouts; keep backup."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

def patched(data):
    nl = b'\r\n' if b'\r\n' in data else b'\n'
    source = data.decode('utf-8').replace('\r\n', '\n')
    if '# full_mission_contract_20261030' in source:
        raise ValueError('already patched')
    marker = '    problems.extend(single_action_problems(commands, task))'
    fallback = '    if best is not None:\n'
    hint = '    return task + hint\n'
    for text in (marker, fallback, hint):
        if source.count(text) != 1:
            raise ValueError('Unsupported mission_once.py layout: ' + repr(text))
    source = source.replace(marker, marker + '\n    problems.extend(full_mission_problems(commands))')
    source = source.replace(fallback,
        '    if strict_contract_enabled():\n'
        '        print("[contract] No valid complete model response; no command published", flush=True)\n'
        '        return None\n' + fallback)
    source = source.replace(hint,
        '    if strict_contract_enabled():\n'
        '        hint += "\\n本轮明确要求完整比赛六阶段，必须按起飞、穿框、识码、逆穿框、指定颜色击球、返航降落顺序生成。"\n' + hint)
    source += '\n' # Imports must precede main invocation, not just be appended.
    source = source.replace('import sys\n', 'import sys\n'
        '# full_mission_contract_20261030\n'
        'from mission_contract import full_mission_problems, strict_contract_enabled\n', 1)
    compile(source, 'mission_once.py', 'exec')
    return source.replace('\n', nl.decode()).encode('utf-8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    data=args.source.read_bytes(); candidate=patched(data)
    manifest={'source':str(args.source.resolve()), 'before_sha256':hashlib.sha256(data).hexdigest(),
              'after_sha256':hashlib.sha256(candidate).hexdigest(), 'applied':args.apply}
    if args.apply:
        backup=args.source.with_suffix('.py.pre_contract_'+manifest['before_sha256'][:12])
        if backup.exists(): raise ValueError('backup already exists')
        module=args.source.parent/'mission_contract.py'
        if module.exists(): raise ValueError('contract module already exists')
        backup.write_bytes(data)
        shutil.copyfile(Path(__file__).with_name('mission_contract.py'),module)
        args.source.write_bytes(candidate)
        args.source.with_suffix('.contract.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest,indent=2))

if __name__=='__main__': main()
