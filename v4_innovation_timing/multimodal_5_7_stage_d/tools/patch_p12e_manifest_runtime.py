#!/usr/bin/env python3
"""Update only the deployed candidate runtime hash in the frozen manifest."""
from pathlib import Path
import hashlib
import shutil
import sys

manifest = Path('/home/ubuntu/multimodal_v2/p12e_stage_b/v2/manifest.json')
backup = Path(sys.argv[1])
expected_old = 'd1fde2bfa8da630393d5009c0e55f49f'
expected_new = '5026dcf152790e962b11ebee577fb792'
raw = manifest.read_text(encoding='utf-8')
if raw.count(expected_old) != 1:
    raise SystemExit('expected exactly one stale runtime hash')
if not backup.exists():
    backup.mkdir(parents=True)
    shutil.copy2(manifest, backup / 'manifest.json.before')
    (backup / 'before_md5.txt').write_text(
        f'{hashlib.md5(manifest.read_bytes()).hexdigest()}  {manifest}\n', encoding='ascii')
manifest.write_bytes(raw.replace(expected_old, expected_new, 1).encode('utf-8'))
(backup / 'after_md5.txt').write_text(
    f'{hashlib.md5(manifest.read_bytes()).hexdigest()}  {manifest}\n', encoding='ascii')
print('manifest_before_runtime=' + expected_old)
print('manifest_after_runtime=' + expected_new)
print('manifest_md5=' + hashlib.md5(manifest.read_bytes()).hexdigest())
