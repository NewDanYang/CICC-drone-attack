from pathlib import Path
import hashlib, shutil, sys, difflib, re
root, backup = map(Path, sys.argv[1:3])
path = Path('src/mission_pkg/src/nodes/action/visual_servo.cpp')
src = (root / path).read_bytes()
text = src.decode('utf-8').replace('\r\n','\n')
if 'sprint_alignment_v1' in text or 'centered_for_sprint' in text:
    raise RuntimeError('Sprint alignment patch already present; no changes made')
# Find candidate if-blocks by scanning every if whose condition mentions both names.
starts = []
for m in re.finditer(r'\bif\s*\([^\n{}]*current_ratio[^\n{}]*approach_area_threshold_[^\n{}]*\)\s*\{', text):
    brace = text.find('{', m.start(), m.end())
    depth = 0; end = None
    for i in range(brace, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0: end = i + 1; break
    if end is not None and 'sprint_start_time_' in text[m.start():end] and 'SPRINT!' in text[m.start():end]:
        starts.append((m.start(), end))
if len(starts) != 1:
    raise RuntimeError('Could not identify unique sprint block; found %d candidates; no changes made' % len(starts))
start, end = starts[0]
old = text[start:end]
indent = re.match(r'[ \t]*', text[text.rfind('\n', 0, start)+1:start]).group(0)
new = indent + 'const bool centered_for_sprint = isCentered();\n' + indent + 'if (current_ratio >= approach_area_threshold_ && centered_for_sprint) {\n' + indent + '    current_state_ = SPRINTING;\n' + indent + '    sprint_start_time_ = ros::Time::now();\n' + indent + '    ROS_INFO("[%s]: Area %.1f%% and centered -> SPRINT! (sprint_vel=%.2f, time=%.1fs)",\n' + indent + '             name().c_str(), current_ratio*100, approach_area_threshold_*100,\n' + indent + '             sprint_velocity_, sprint_time_);\n' + indent + '} else if (current_ratio >= approach_area_threshold_ && !centered_for_sprint) {\n' + indent + '    ROS_WARN_THROTTLE(0.5,\n' + indent + '        "[%s]: Area %.1f%% reached but target is off-center (err_x=%.0f err_y=%.0f); continue aligning.",\n' + indent + '        name().c_str(), current_ratio*100, err_x, err_y);\n' + indent + '}'
patched = text[:start] + new + text[end:]
backup.mkdir(parents=True, exist_ok=False)
(backup / path).parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / path, backup / path)
(backup / 'before_sha256.txt').write_text(hashlib.sha256(src).hexdigest()+'  '+str(path)+'\n', encoding='ascii')
(backup / 'changes.diff').write_text(''.join(difflib.unified_diff(text.splitlines(True), patched.splitlines(True), fromfile=str(path), tofile=str(path)+'.patched')), encoding='utf-8')
data = patched.replace('\n','\r\n') if b'\r\n' in src and src.count(b'\r\n') == src.count(b'\n') else patched
(root / path).write_bytes(data.encode('utf-8'))
(backup / 'restore.sh').write_text('#!/usr/bin/env bash\nset -e\ncp -p "'+str(backup/path)+'" "'+str(root/path)+'"\ncd "'+str(root)+'"\ncatkin_make --pkg mission_pkg -j2\n', encoding='utf-8')
print('Patched:', path); print('Backup:', backup)
