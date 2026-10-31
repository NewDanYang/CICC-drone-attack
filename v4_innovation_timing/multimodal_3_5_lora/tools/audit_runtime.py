"""Read-only integrity record; no environment variables or credentials are collected."""
import hashlib,importlib.metadata,json,sys
from pathlib import Path
ROOT=Path('/root/gpufree-data/tcei_lora35')
files=['/home/ubuntu/model/mission_once.py',
 '/home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp',
 '/home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros',
 '/home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch',
 '/home/ubuntu/catkin_ws/src/mission_pkg/include/base/drone_action_node.h',
 '/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp',
 '/home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/action/visual_servo.h',
 '/home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/goto.cpp',
 '/home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/action/goto.h',
 '/home/ubuntu/catkin_ws/src/mission_pkg/src/mavros_cnt.cpp',
 '/home/ubuntu/catkin_ws/src/sensor_pkg/Config.json']
files+= [str(p) for p in Path('/home/ubuntu/model/FM9G4B-V').glob('*.py')]
files+= [str(p) for p in Path('/home/ubuntu/model/FM9G4B-V').glob('*.json')]
result=dict(files={s:dict(md5=hashlib.md5(Path(s).read_bytes()).hexdigest(),
    sha256=hashlib.sha256(Path(s).read_bytes()).hexdigest()) for s in files},
    demo_packages={name:importlib.metadata.version(name) for name in ['torch','transformers','accelerate','numpy']})
dest=ROOT/(sys.argv[1]+'.json')
if dest.exists():raise RuntimeError('Refuse overwrite')
dest.write_text(json.dumps(result,indent=2)+'\n');print(dest)
