"""Read-only flight/recognition audit and actual X11-window capture.

This process emits no ROS messages and sends no simulator commands. It raises
the actual perception window before capture so covered X11 pixels are visible.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import threading
import time

import cv2
import numpy as np
import rospy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from rosgraph_msgs.msg import Log
from common_msgs.msg import Objects,DetEnable
from mavros_msgs.msg import PositionTarget
from nav_msgs.msg import Odometry


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'frames').mkdir();(args.output/'screenshots').mkdir()
    output=(args.output/'events.jsonl').open('w',encoding='utf-8',buffering=1)
    lock=threading.Lock()
    state={'active':False,'last_image':0.,'last_control':0.,'last_odom':0.,'counter':0,
           'valid_model':0.,'stop':False}
    def record(kind,**data):
        with lock:
            output.write(json.dumps(dict(wall_time=datetime.now(timezone.utc).isoformat(),
                ros_time=rospy.Time.now().to_sec(),event=kind,**data),ensure_ascii=False)+'\n')
    def rosout(msg):
        if msg.name=='/llm_mission_node' or 'MULTIMODAL' in msg.msg or 'SAFE' in msg.msg:
            record('rosout',node=msg.name,message=msg.msg,stamp=msg.header.stamp.to_sec(),level=msg.level)
        if 'Visual Servo Started' in msg.msg or 'MULTIMODAL_STAGE_START' in msg.msg:
            state['active']=True
        if 'MULTIMODAL_STAGE_STOP' in msg.msg:
            state['active']=False
    def control(msg):
        now=time.monotonic()
        if now-state['last_control']<0.05: return
        state['last_control']=now
        record('setpoint',stamp=msg.header.stamp.to_sec(),coordinate_frame=msg.coordinate_frame,
               type_mask=msg.type_mask,position=[msg.position.x,msg.position.y,msg.position.z],
               velocity=[msg.velocity.x,msg.velocity.y,msg.velocity.z],yaw=msg.yaw,yaw_rate=msg.yaw_rate)
    def odom(msg,topic='mavros'):
        now=time.monotonic()
        key='last_odom_'+topic
        if now-state.get(key,0.)<0.1: return
        state[key]=now
        p=msg.pose.pose.position;q=msg.pose.pose.orientation
        record('odom' if topic=='mavros' else 'rfly_odom',stamp=msg.header.stamp.to_sec(),
               position=[p.x,p.y,p.z],quaternion=[q.x,q.y,q.z,q.w])
    def objects(msg,topic):
        if topic=='multimodal' and msg.objects: state['valid_model']=time.monotonic()
        record('objects',topic=topic,stamp=msg.header.stamp.to_sec(),frame_id=msg.header.frame_id,
               seq=msg.header.seq,objects=[dict(name=o.class_name,score=o.score,center=[o.center_x,o.center_y],
                 bbox=[o.left_top_x,o.left_top_y,o.right_bottom_x,o.right_bottom_y]) for o in msg.objects])
    def image(msg):
        now=time.monotonic()
        interval=0.085 if state['active'] else 0.95
        if now-state['last_image']<interval: return
        state['last_image']=now
        channels=4 if msg.encoding in ('rgba8','bgra8') else 3
        if msg.encoding not in ('rgb8','bgr8','rgba8','bgra8'): return
        rows=np.frombuffer(msg.data,dtype=np.uint8).reshape(msg.height,msg.step)
        pixels=rows[:,:msg.width*channels].reshape(msg.height,msg.width,channels)[:,:,:3]
        bgr=(pixels[:,:,::-1] if msg.encoding.startswith('rgb') else pixels).copy()
        state['counter']+=1
        path=args.output/'frames'/f'{state["counter"]:06d}.jpg'
        cv2.imwrite(str(path),bgr,[cv2.IMWRITE_JPEG_QUALITY,92])
        record('image',file=str(path.relative_to(args.output)),header_stamp=msg.header.stamp.to_sec(),
               header_seq=msg.header.seq,encoding=msg.encoding,width=msg.width,height=msg.height,
               active=state['active'],sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
               rgb_pixels_sha256=hashlib.sha256(bgr[:,:,::-1].tobytes()).hexdigest())
    def mission_result(msg):
        state['active']=False
        record('mission_result',value=msg.data)
    rospy.init_node('multimodal_trial_audit',anonymous=True,disable_signals=True)
    rospy.Subscriber('/rosout',Log,rosout,queue_size=500)
    rospy.Subscriber('/mavros/setpoint_raw/local',PositionTarget,control,queue_size=100)
    rospy.Subscriber('/mavros/local_position/odom',Odometry,odom,queue_size=10)
    rospy.Subscriber('/rflysim/uav1/local/odom',Odometry,lambda msg:odom(msg,'rfly'),queue_size=10)
    rospy.Subscriber('/objects',Objects,lambda msg:objects(msg,'yolo'),queue_size=100)
    rospy.Subscriber('/multimodal/objects',Objects,lambda msg:objects(msg,'multimodal'),queue_size=100)
    rospy.Subscriber('/detect_ctrl',DetEnable,lambda msg:record('detect_gate',enabled=msg.is_open),queue_size=50)
    rospy.Subscriber('/mission_result',String,mission_result,queue_size=10)
    rospy.Subscriber('/mission_command',String,lambda msg:record('mission_command',value=msg.data),queue_size=10)
    rospy.Subscriber('/rflysim/sensor1/img_rgb',Image,image,queue_size=1,buff_size=4*1024*1024)
    signal.signal(signal.SIGTERM,lambda *_:state.update(stop=True))
    signal.signal(signal.SIGINT,lambda *_:state.update(stop=True))
    (args.output/'ready').write_text('1\n')
    index=0
    last_capture=0.
    while not rospy.is_shutdown() and not state['stop']:
        if time.monotonic()-state['valid_model']<1.0 and time.monotonic()-last_capture>=2.:
            try:
                windows=subprocess.run(['wmctrl','-l'],capture_output=True,text=True,timeout=3,check=True)
                matches=[line.split()[0] for line in windows.stdout.splitlines() if 'FM9G balloon perception' in line]
                if matches:
                    index+=1
                    subprocess.run(['wmctrl','-ir',matches[-1],'-e','0,20,20,-1,-1'],check=True,timeout=2)
                    subprocess.run(['wmctrl','-ia',matches[-1]],check=True,timeout=2)
                    time.sleep(.1)
                    raw=args.output/'screenshots'/'capture.xwd'
                    target=args.output/'screenshots'/f'window_{index:04d}.png'
                    subprocess.run(['xwd','-silent','-id',matches[-1],'-out',str(raw)],check=True,timeout=3)
                    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(raw),
                        '-frames:v','1',str(target)],check=True,timeout=5)
                    raw.unlink()
                    captured=cv2.imread(str(target))
                    h,w=captured.shape[:2]
                    nonblank=bool(np.max(captured[h//5:4*h//5,w//10:9*w//10])>1)
                    record('window_screenshot' if nonblank else 'blank_window_screenshot',
                           window_id=matches[-1],file=str(target.relative_to(args.output)),
                           sha256=hashlib.sha256(target.read_bytes()).hexdigest(),nonblank=nonblank,
                           capture_method='xwd_window_after_raise')
                    last_capture=time.monotonic()
            except Exception as exc: record('screenshot_error',error=repr(exc))
        time.sleep(.1)
    record('observer_stopped')


if __name__=='__main__': main()
