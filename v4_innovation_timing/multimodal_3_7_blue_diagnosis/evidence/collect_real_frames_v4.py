#!/usr/bin/env python3
"""Collect real RGB frames with the sealed planner parameters untouched.

This copy intentionally has no command-speed cap or planner parameter override.
It publishes only local-position setpoints, records odometry speed, and leaves
the running simulation's official 0.35 m/s parameters unchanged.
"""
import argparse, datetime as dt, json, math, os, threading, time
from pathlib import Path
import cv2, numpy as np, rospy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import State, PositionTarget
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image
from common_msgs.msg import Objects

def iso(t=None):
    return dt.datetime.fromtimestamp(time.time() if t is None else t, dt.timezone.utc).isoformat()
def yaw_q(q): return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))

class Collector:
    def __init__(self, out, interval):
        self.out=Path(out); self.out.mkdir(parents=True,exist_ok=False)
        self.interval=interval; self.lock=threading.RLock(); self.last_image=0
        self.odom=None; self.state=State(); self.objects=[]; self.image_count=0
        self.events=(self.out/'events.jsonl').open('w',encoding='utf-8',buffering=1)
        self.odomlog=(self.out/'odom.jsonl').open('w',encoding='utf-8',buffering=1)
        self.pub=rospy.Publisher('/mavros/setpoint_raw/local',PositionTarget,queue_size=10)
        rospy.Subscriber('/mavros/state',State,self.on_state,queue_size=1)
        rospy.Subscriber('/mavros/local_position/odom',Odometry,self.on_odom,queue_size=5)
        rospy.Subscriber('/rflysim/sensor1/img_rgb',Image,self.on_image,queue_size=2,buff_size=4*1024*1024)
        rospy.Subscriber('/objects',Objects,self.on_objects,queue_size=5)
        self.log('collector_start',dict(image_topic='/rflysim/sensor1/img_rgb',
            proposal_topic='/objects',sealed_planner_max_vel=0.35,
            speed_override=None,camera_encoding='raw ROS Image saved as PNG',interval_s=interval))
    def log(self,event,data):
        self.events.write(json.dumps(dict(wall_time=iso(),event=event,**data),ensure_ascii=False)+'\n');self.events.flush()
    def on_state(self,m):
        with self.lock:self.state=m
    def on_odom(self,m):
        p=m.pose.pose.position; q=m.pose.pose.orientation; v=m.twist.twist.linear
        row=dict(wall_time=iso(),x=p.x,y=p.y,z=p.z,yaw=yaw_q(q),vx=v.x,vy=v.y,vz=v.z,
                 speed=math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z))
        with self.lock:self.odom=row
        self.odomlog.write(json.dumps(row)+'\n');self.odomlog.flush()
    def on_objects(self,m):
        vals=[]
        for o in m.objects:
            vals.append(dict(class_name=o.class_name,left=o.left_top_x,top=o.left_top_y,
                right=o.right_bottom_x,bottom=o.right_bottom_y,center_x=o.center_x,center_y=o.center_y,score=o.score))
        with self.lock:self.objects=vals
    def on_image(self,m):
        now=time.time()
        with self.lock:
            if now-self.last_image<self.interval:return
            self.last_image=now; self.image_count+=1; idx=self.image_count; pose=self.odom; props=list(self.objects)
        if m.encoding not in ('rgb8','bgr8') or m.step<m.width*3:
            self.log('image_rejected',dict(encoding=m.encoding,width=m.width,height=m.height));return
        arr=np.frombuffer(m.data,np.uint8).reshape(m.height,m.step)[:,:m.width*3].reshape(m.height,m.width,3)
        if m.encoding=='rgb8':arr=cv2.cvtColor(arr,cv2.COLOR_RGB2BGR)
        name=f'frame_{idx:05d}.png'; path=self.out/name
        if not cv2.imwrite(str(path),arr):raise RuntimeError('imwrite failed '+str(path))
        self.log('frame',dict(image=name,width=m.width,height=m.height,encoding=m.encoding,
            source_stamp=dict(secs=m.header.stamp.secs,nsecs=m.header.stamp.nsecs),odom=pose,proposals=props))
    def command(self,enu,yaw):
        p=PositionTarget();p.header.stamp=rospy.Time.now();p.coordinate_frame=PositionTarget.FRAME_LOCAL_NED
        p.type_mask=(PositionTarget.IGNORE_VX|PositionTarget.IGNORE_VY|PositionTarget.IGNORE_VZ|
                     PositionTarget.IGNORE_YAW_RATE|PositionTarget.IGNORE_AFX|PositionTarget.IGNORE_AFY|
                     PositionTarget.IGNORE_AFZ|PositionTarget.FORCE)
        p.position.x=enu[0];p.position.y=enu[1];p.position.z=enu[2];p.yaw=yaw
        self.pub.publish(p)
    def hold(self,enu,yaw,duration):
        end=time.time()+duration
        while not rospy.is_shutdown() and time.time()<end:self.command(enu,yaw);rospy.sleep(.05)
    def wait_arrival(self,enu,yaw,timeout=45,tol=.18):
        start=time.time();stable=0
        while not rospy.is_shutdown() and time.time()-start<timeout:
            self.command(enu,yaw);rospy.sleep(.05)
            with self.lock:p=self.odom
            if p:
                d=math.sqrt(sum((p[k]-enu[i])**2 for i,k in enumerate(('x','y','z'))))
                stable=stable+1 if d<=tol else 0
                if stable>=30:
                    self.log('waypoint_arrived',dict(target=enu,yaw=yaw,elapsed_s=time.time()-start,position=p));return True
        with self.lock:p=self.odom
        self.log('waypoint_timeout',dict(target=enu,yaw=yaw,elapsed_s=time.time()-start,position=p));return False
    def shutdown(self):
        self.log('collector_end',dict(images=self.image_count));self.events.close();self.odomlog.close()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);ap.add_argument('--interval',type=float,default=.25);a=ap.parse_args()
    rospy.init_node('mm37_real_frame_collector_hold',anonymous=False); c=Collector(a.output,a.interval)
    try:
        waypoints=[((0,0,1.0),0.0),((0,1.2,1.0),math.pi/2),((5.0,1.2,1.0),0.0),
                   ((5.0,2.6,1.0),math.pi/2),((0.5,2.6,1.0),math.pi),
                   ((0.5,-2.6,1.0),-math.pi/2),((4.8,-2.6,1.0),0.0),
                   ((4.8,-1.2,1.0),math.pi/2),((0.5,-1.2,1.0),math.pi),
                   ((0.5,0.0,1.0),math.pi/2),((4.8,0.0,1.0),0.0),((0,0,.8),math.pi)]
        c.hold(waypoints[0][0],waypoints[0][1],4.0)
        setmode=rospy.ServiceProxy('/mavros/set_mode',SetMode); arm=rospy.ServiceProxy('/mavros/cmd/arming',CommandBool)
        mode=setmode(custom_mode='OFFBOARD');c.log('offboard_request',dict(mode_sent=mode.mode_sent));rospy.sleep(.5)
        ar=arm(value=True);c.log('arm_request',dict(success=ar.success))
        if not ar.success:raise RuntimeError('arming failed')
        for target,yaw in waypoints[1:]:
            if not c.wait_arrival(target,yaw):raise RuntimeError('waypoint timeout')
            c.hold(target,yaw,6.0)
        c.wait_arrival((0,0,.8),math.pi);c.hold((0,0,.8),math.pi,2)
        try:
            land=rospy.ServiceProxy('/mavros/cmd/land',CommandTOL);resp=land(altitude=0.0,latitude=0.0,longitude=0.0,min_pitch=0.0,yaw=0.0)
            c.log('land_request',dict(success=resp.success))
        except Exception as e:c.log('land_request_error',dict(error=repr(e)))
        rospy.sleep(8)
        try:resp=arm(value=False);c.log('disarm_request',dict(success=resp.success))
        except Exception as e:c.log('disarm_error',dict(error=repr(e)))
    finally:c.shutdown()
if __name__=='__main__':main()
