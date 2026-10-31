#!/usr/bin/env python3
"""Drive the real PerceptionBridge with recorded RGB frames without ROS flight."""
import json
import os
import shutil
import sys
import time
import types
from pathlib import Path

import cv2


class Stamp:
    def __init__(self, value): self.value = float(value)
    def to_sec(self): return self.value


class Header:
    def __init__(self, stamp=0.0): self.stamp = Stamp(stamp); self.seq = 0; self.frame_id = ''


class ImageMsg:
    def __init__(self, bgr, stamp):
        self.header = Header(stamp); self.height, self.width = bgr.shape[:2]
        self.encoding = 'bgr8'; self.step = self.width * 3; self.data = bgr.tobytes()


class StringMsg:
    def __init__(self, data=''): self.data = data


class ObjMsg:
    def __init__(self): self.header = Header(); self.class_name=''; self.score=0.0


class ObjectsMsg:
    def __init__(self): self.header=Header(); self.source_id=0; self.objects=[]


class DetEnableMsg:
    def __init__(self): self.is_open=True


class FakePublisher:
    def __init__(self, topic): self.topic=topic; self.messages=[]
    def publish(self, message): self.messages.append(message)


class FakeSubscriber:
    def unregister(self): pass


class FakeRospy(types.ModuleType):
    def __init__(self): super().__init__('rospy'); self.publishers=[]
    def Publisher(self, topic, *args, **kwargs):
        p=FakePublisher(topic); self.publishers.append(p); return p
    def Subscriber(self, *args, **kwargs): return FakeSubscriber()
    def loginfo(self, *args, **kwargs): pass
    def logwarn(self, *args, **kwargs): pass
    def logerr(self, *args, **kwargs): pass
    def loginfo_throttle(self, *args, **kwargs): pass
    def logwarn_throttle(self, *args, **kwargs): pass
    def logerr_throttle(self, *args, **kwargs): pass
    def is_shutdown(self): return False


rospy = FakeRospy()
rospy.Time = types.SimpleNamespace(from_sec=lambda v: Stamp(v), now=lambda: Stamp(time.time()))
sys.modules['rospy'] = rospy

sensor_msgs = types.ModuleType('sensor_msgs'); sensor_msgs_msg = types.ModuleType('sensor_msgs.msg'); sensor_msgs_msg.Image=ImageMsg
sensor_msgs.msg=sensor_msgs_msg; sys.modules['sensor_msgs']=sensor_msgs; sys.modules['sensor_msgs.msg']=sensor_msgs_msg
std_msgs = types.ModuleType('std_msgs'); std_msgs_msg = types.ModuleType('std_msgs.msg'); std_msgs_msg.String=StringMsg
std_msgs.msg=std_msgs_msg; sys.modules['std_msgs']=std_msgs; sys.modules['std_msgs.msg']=std_msgs_msg
common_msgs = types.ModuleType('common_msgs'); common_msgs_msg = types.ModuleType('common_msgs.msg')
common_msgs_msg.Objects=ObjectsMsg; common_msgs_msg.Obj=ObjMsg; common_msgs_msg.DetEnable=DetEnableMsg
common_msgs.msg=common_msgs_msg; sys.modules['common_msgs']=common_msgs; sys.modules['common_msgs.msg']=common_msgs_msg

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('fm9g_perception'); pkg.__path__=[str(ROOT/'v2')]; sys.modules['fm9g_perception']=pkg
from fm9g_perception.runtime import PerceptionBridge
from transformers import AutoModel, AutoProcessor, AutoTokenizer
import torch

if len(sys.argv) != 3:
    raise SystemExit('usage: replay_runtime_smoke.py P12E_JSON RUN_AUDIT_DIR')
p12_path, audit_dir = map(Path, sys.argv[1:])
rows = json.loads(p12_path.read_text())['rows']
events = [json.loads(line) for line in (audit_dir/'events.jsonl').open()]
start = next(e['ros_time'] for e in events if e['event']=='rosout' and 'Visual Servo Started' in e.get('message',''))
frames = [e for e in events if e['event']=='image' and start-2 <= e['ros_time'] <= start+50 and (audit_dir/e['file']).exists()]
limit=int(os.environ.get('SMOKE_MAX_FRAMES','0'))
if limit: frames=frames[:limit]
skip=int(os.environ.get('SMOKE_SKIP_FIRST','0'))
if skip:
    frames=frames[skip:]
    rows=rows[skip:]
if not frames: raise SystemExit('no recorded frames')

model_dir='/home/ubuntu/model/FM9G4B-V'
tok=AutoTokenizer.from_pretrained(model_dir,trust_remote_code=True,local_files_only=True)
proc=AutoProcessor.from_pretrained(model_dir,trust_remote_code=True,local_files_only=True)
proc.image_processor.scale_resolution=224
model=AutoModel.from_pretrained(model_dir,trust_remote_code=True,local_files_only=True,torch_dtype=torch.bfloat16).cuda().eval()
model_lock=__import__('threading').Lock()
os.environ['MULTIMODAL_EVIDENCE_ROOT']='/tmp/p12e_runtime_smoke'
shutil.rmtree('/tmp/p12e_runtime_smoke', ignore_errors=True)
bridge=PerceptionBridge(model,tok,proc,model_lock)
session='smoke-session'; color=p12_path.name.split('_')[2]
bridge.on_gate(StringMsg(json.dumps({'action':'start','session':session,'color':color})))
previous_stamp = frames[0]['header_stamp']
first_frame = True
for event in frames:
    delay=max(0.0, event['header_stamp']-previous_stamp)
    if delay: time.sleep(delay)
    bgr=cv2.imread(str(audit_dir/event['file']))
    bridge.on_image(ImageMsg(bgr,event['header_stamp']))
    if first_frame:
        time.sleep(0.1)
        first_frame = False
    previous_stamp=event['header_stamp']
time.sleep(3.0)
bridge.close()

audit_file=next(Path('/tmp/p12e_runtime_smoke').rglob('audit.jsonl'))
published=[]
for line in audit_file.open():
    event=json.loads(line)
    if event.get('kind')=='publish' and isinstance(event.get('bbox'),list):
        published.append(event)
ref={i+1:r for i,r in enumerate(rows)}
diffs=[]
for event in published:
    refrow=ref.get(event['frame_seq'])
    if refrow and isinstance(refrow.get('pub'),list):
        a=event['bbox']; b=refrow['pub']
        diffs.append(((a[0]+a[2]-b[0]-b[2])/2, (a[1]+a[3]-b[1]-b[3])/2))
norm=max(((x*x+y*y)**0.5 for x,y in diffs), default=None)
result={'frames':len(frames),'runtime_publishes':len(published),'matched_boxes':len(diffs),
        'max_center_difference_px':norm,'audit_path':str(audit_file)}
print(json.dumps(result,indent=2))
if norm is not None and norm>3.0:
    raise SystemExit('runtime replay differs from P12e by >3 px')
