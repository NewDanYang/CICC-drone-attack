from pathlib import Path
import hashlib, shutil, sys, difflib
root, backup = map(Path, sys.argv[1:3])
path = Path('src/mission_pkg/src/nodes/action/visual_servo.cpp')
src = (root / path).read_bytes()
text = src.decode('utf-8').replace('\r\n','\n')
if 'yaw_direction_v1' in text:
    raise RuntimeError('Yaw direction patch already present; no changes made')
old = 'double yaw_rate = -(k_p_yaw_rate_ * err_after_dz + k_d_yaw_rate_ * d_err);'
if text.count(old) != 1:
    raise RuntimeError('Expected one yaw-rate equation; no changes made')
if 'centered_for_sprint' not in text:
    raise RuntimeError('Sprint alignment patch missing; no changes made')
new = '// yaw_direction_v1: image error sign follows the simulator camera yaw convention.\n    double yaw_rate = (k_p_yaw_rate_ * err_after_dz + k_d_yaw_rate_ * d_err);'
patched = text.replace(old,new,1)
backup.mkdir(parents=True, exist_ok=False)
(backup / path).parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / path, backup / path)
(backup / 'before_sha256.txt').write_text(hashlib.sha256(src).hexdigest()+'  '+str(path)+'\n', encoding='ascii')
(backup / 'changes.diff').write_text(''.join(difflib.unified_diff(text.splitlines(True),patched.splitlines(True),fromfile=str(path),tofile=str(path)+'.patched')), encoding='utf-8')
data = patched.replace('\n','\r\n') if b'\r\n' in src and src.count(b'\r\n') == src.count(b'\n') else patched
(root / path).write_bytes(data.encode('utf-8'))
(backup / 'restore.sh').write_text('#!/usr/bin/env bash\nset -e\ncp -p "'+str(backup/path)+'" "'+str(root/path)+'"\ncd "'+str(root)+'"\ncatkin_make --pkg mission_pkg -j2\n', encoding='utf-8')
print('Patched:', path); print('Backup:', backup)
