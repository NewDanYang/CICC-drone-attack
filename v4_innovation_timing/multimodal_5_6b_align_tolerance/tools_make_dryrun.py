from pathlib import Path
import hashlib,difflib
src=Path('v3_stability/hit_balloon_v2/deployed_source/visual_servo.cpp')
text=src.read_text(encoding='utf-8')
old=hashlib.md5(src.read_bytes()).hexdigest()
trial=text.replace('InputPort<double>("deadzone_yaw", 8.0,', 'InputPort<double>("deadzone_yaw", 20.0,',1).replace('InputPort<double>("deadzone_vz", 10.0,', 'InputPort<double>("deadzone_vz", 20.0,',1)
assert trial != text and trial.count('deadzone_yaw", 20.0')==1 and trial.count('deadzone_vz", 20.0')==1
Path('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence/deadzone_20_dryrun.diff').write_text(''.join(difflib.unified_diff(text.splitlines(True),trial.splitlines(True),fromfile='frozen/visual_servo.cpp',tofile='trial20/visual_servo.cpp')),encoding='utf-8')
Path('v4_innovation_timing/multimodal_5_6b_align_tolerance/evidence/frozen_snapshot_md5.txt').write_text(f'{old}  v3_stability/hit_balloon_v2/deployed_source/visual_servo.cpp\nd3324b0458b2160102f9bbf44546d035  v3_stability/hit_balloon_v2/deployed_source/visual_servo.h\n',encoding='ascii')
