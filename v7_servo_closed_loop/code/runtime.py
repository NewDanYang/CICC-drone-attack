"""Same-process FM9G perception bridge; this module never commands flight."""
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

import cv2
import numpy as np
from PIL import Image as PILImage
import rospy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from common_msgs.msg import Objects, Obj, DetEnable

from nav_msgs.msg import Odometry

from .tracking import Frame, ReplayTracker
from .presence import NativePresenceSweep
from .v5_guard import PublishGuard
from .v6_estimator import TargetEstimator

COLOR_TEXT = {'red': '红色', 'purple': '紫色', 'blue': '蓝色'}


class StageInactive(Exception):
    pass


class AuditedProcessor:
    def __init__(self,processor,audit):
        self.processor=processor
        self.audit=audit

    def __getattr__(self,name):
        return getattr(self.processor,name)

    def __call__(self,prompts,images,**kwargs):
        counts=[len(group) for group in images]
        if not counts or any(count!=1 for count in counts):
            raise ValueError(f'Image contract violation: {counts}')
        self.audit(kind='processor_input',images_per_item=counts)
        return self.processor(prompts,images,**kwargs)


def decode_bgr(msg):
    channels={'rgb8':3,'bgr8':3,'rgba8':4,'bgra8':4}.get(msg.encoding)
    if channels is None or msg.step<msg.width*channels or len(msg.data)!=msg.height*msg.step:
        raise ValueError('Unsupported/malformed RGB image')
    rows=np.frombuffer(msg.data,dtype=np.uint8).reshape(msg.height,msg.step)
    array=rows[:,:msg.width*channels].reshape(msg.height,msg.width,channels)[:,:,:3]
    return (array[:,:,::-1] if msg.encoding.startswith('rgb') else array).copy()


class PerceptionBridge:
    def __init__(self,model,tokenizer,processor,model_lock):
        import torch
        cv2.setNumThreads(2)
        self.model,self.tokenizer,self.model_lock=model,tokenizer,model_lock
        self.lock=threading.RLock()
        self.log_lock=threading.Lock()
        self.stop_event=threading.Event()
        self.frames=deque(maxlen=200)
        self.frame_counter=0
        self.session=None
        self.color=None
        self.epoch=0
        self.pending=None
        self.current=None
        self.model_track=None
        self.track_misses=0
        self.latest_display=None
        # A recorded window can begin one second before the visual-servo
        # marker; the publication gate still rejects frames older than 0.35 s.
        self.tracker=ReplayTracker(cv2,max_semantic_age=12.0,max_gap=1.5)
        self.last_inference_seq=-1
        self.last_snapshot=0.0
        self.result_seen=False
        self.window_name='FM9G balloon perception'
        root=os.environ.get('MULTIMODAL_EVIDENCE_ROOT','/home/ubuntu/tcei_baseline_tools/results/multimodal_v2')
        self.output=Path(root)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_')+uuid.uuid4().hex[:6])
        (self.output/'images').mkdir(parents=True)
        (self.output/'window').mkdir()
        self.log=(self.output/'audit.jsonl').open('w',encoding='utf-8',buffering=1)
        self.processor=AuditedProcessor(processor,self.audit)
        if hasattr(processor,'image_processor') and hasattr(processor.image_processor,'scale_resolution'):
            processor.image_processor.scale_resolution=224
        thresholds=tuple(float(v) for v in os.environ.get(
            'MULTIMODAL_PRESENCE_THRESHOLDS','0.4,0.5,0.5,0.4').split(','))
        if len(thresholds)!=4:
            raise ValueError('MULTIMODAL_PRESENCE_THRESHOLDS needs four values')
        self.presence=NativePresenceSweep(
            model,tokenizer,self.processor,model_lock,self.audit,self.active,
            res=224,n_initial=8,n_track=7,window_factor=2.2,
            thresholds=thresholds)
        self.presence.warmup()
        # L1/L2 guard: what the bridge publishes between model decisions.
        self.odom_z=None
        # v6: the model box is the only measurement; the estimator carries it
        # forward with pose compensation instead of a CSRT between decisions.
        self.est=TargetEstimator(self.audit)
        self.guard=(PublishGuard()
                    if os.environ.get('MULTIMODAL_V5_GUARD','1')=='1' else None)
        self.semantic_hold_s=1.5
        self.objects_pub=rospy.Publisher('/multimodal/objects',Objects,queue_size=1)
        self.debug_pub=rospy.Publisher('/multimodal/debug_image',Image,queue_size=1)
        self.det_gate=rospy.Publisher('/detect_ctrl',DetEnable,queue_size=2,latch=True)
        self.image_topic='/rflysim/sensor1/img_rgb'
        self.subs=[rospy.Subscriber(self.image_topic,Image,self.on_image,queue_size=1,buff_size=4*1024*1024),
                   rospy.Subscriber('/multimodal/balloon_target',String,self.on_gate,queue_size=5),
                   rospy.Subscriber('/mission_result',String,self.on_result,queue_size=2),
                   rospy.Subscriber('/mavros/local_position/odom',Odometry,self.on_pose,queue_size=1)]
        self.workers=[threading.Thread(target=self.inference_loop,name='fm9g-image-worker'),
                      threading.Thread(target=self.tracking_loop,name='fm9g-tracking-worker')]
        for worker in self.workers: worker.start()
        self.audit(kind='ready',image_topic=self.image_topic,model_instance=id(model),
                   output=str(self.output),semantic_hold_s=12.0,frame_hold_s=0.35,
                   torch_threads=torch.get_num_threads(),torch_interop_threads=torch.get_num_interop_threads(),
                   opencv_threads=cv2.getNumThreads(),pid=os.getpid())
        rospy.loginfo('MULTIMODAL_V2_READY evidence=%s image=%s',self.output,self.image_topic)

    def audit(self,**event):
        event.update(wall_time=datetime.now(timezone.utc).isoformat(),monotonic=time.monotonic())
        with self.log_lock:
            self.log.write(json.dumps(event,ensure_ascii=False)+'\n')

    def on_pose(self,msg):
        self.odom_z=msg.pose.pose.position.z
        q=msg.pose.pose.orientation
        position=msg.pose.pose.position
        yaw=math.atan2(2.0*(q.w*q.z+q.x*q.y),1.0-2.0*(q.y*q.y+q.z*q.z))
        self.est.on_pose(time.monotonic(),position.x,position.y,position.z,yaw)

    def on_image(self,msg):
        acquired=time.monotonic()
        header_stamp=msg.header.stamp.to_sec()
        stamp=header_stamp if header_stamp>0 else rospy.Time.now().to_sec()
        try: bgr=decode_bgr(msg)
        except Exception as exc:
            rospy.logwarn_throttle(2.0,'MULTIMODAL_IMAGE_ERROR %s',exc)
            return
        with self.lock:
            if msg.width!=640 or msg.height!=480:
                rospy.logerr_throttle(5.0,'MULTIMODAL_CAMERA_GEOMETRY_MISMATCH %sx%s',msg.width,msg.height)
                return
            self.frame_counter+=1
            self.frames.append(Frame(self.frame_counter,stamp,acquired,bgr))
            first=self.frame_counter==1
        if first:
            self.audit(kind='camera_contract',topic=self.image_topic,encoding=msg.encoding,
                       width=msg.width,height=msg.height,step=msg.step,header_stamp=header_stamp,
                       pixel_clock='camera_header' if header_stamp>0 else 'ros_receive',
                       note='Monotonic acquisition age always starts at ROS receipt, never inference completion')

    def on_gate(self,msg):
        try:
            value=json.loads(msg.data)
            action,session=value['action'],value['session']
            color=value.get('color')
            if not isinstance(session,str) or not session:
                raise ValueError('No session')
            with self.lock:
                if action=='start':
                    if color not in ('red','purple','blue'): raise ValueError('Invalid color')
                    if session==self.session and color==self.color: return
                    self.session,self.color=session,color
                elif action=='stop':
                    if session!=self.session: return
                    self.session=self.color=None
                else: raise ValueError('Invalid action')
                self.epoch+=1
                self.pending=self.current=None
                self.model_track=None
                self.track_misses=0
                self.last_inference_seq=-1
            gate=DetEnable(); gate.is_open=action!='start'
            self.det_gate.publish(gate)
            self.audit(kind='gate',action=action,session=session,color=color,epoch=self.epoch,
                       detector_enabled=gate.is_open)
            rospy.loginfo('MULTIMODAL_GATE_V2 action=%s session=%s color=%s',action,session,color)
        except Exception as exc:
            rospy.logwarn('MULTIMODAL_GATE_REJECT %s',exc)

    def on_result(self,msg):
        with self.lock: session=self.session
        if session:
            self.on_gate(String(data=json.dumps({'action':'stop','session':session})))
        self.audit(kind='mission_result',value=msg.data)
        self.result_seen=True

    def active(self,epoch):
        with self.lock:
            return self.epoch==epoch and self.session is not None and not self.stop_event.is_set()

    def inference_loop(self):
        import torch
        while not self.stop_event.wait(0.02):
            with self.lock:
                if self.session is None or not self.frames:
                    continue
                # The tracking worker must consume the previous model result
                # before the next cycle chooses acquire versus track.  Without
                # this handoff gate, a result can be overwritten by a second
                # acquire while the tracker thread is still initializing.
                if self.pending is not None:
                    continue
                frame=self.frames[-1]
                epoch,session,color=self.epoch,self.session,self.color
                # v6: the crop window is the last model box carried forward by
                # pose, so the newest frame is the correct frame.  Sweeping the
                # anchor frame instead cost ~0.38 s of the 0.9 s source age.
                current=self.model_track.copy() if self.model_track else None
                if frame.seq==self.last_inference_seq:
                    continue
                self.last_inference_seq=frame.seq
            decision=uuid.uuid4().hex[:12]
            image=PILImage.fromarray(cv2.cvtColor(frame.bgr,cv2.COLOR_BGR2RGB))
            image_path=self.output/'images'/(decision+'.png')
            image.save(image_path)
            self.audit(kind='model_source',decision=decision,session=session,color=color,
                       frame_seq=frame.seq,stamp=frame.stamp,acquired=frame.acquired,
                       image=str(image_path.relative_to(self.output)),
                       image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                       pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                       size=image.size,source_mode='native_presence_sweep')
            text=f"这张图片里有没有{COLOR_TEXT[color]}的气球？只回答“是”或“否”。"
            start=time.monotonic()
            try:
                crop=self.est.crop_params(frame.acquired) if current else None
                if crop is not None:
                    side=crop['side']*(1.5 if crop['stale_s']>self.est.MAX_AGE_S else 1.0)
                    # The predicted centre can be wrong, so keep the last
                    # measured centre as a second hypothesis while the
                    # measurement still describes this scene (v7.0).
                    alt=crop.get('alt_center') if crop['stale_s']<2.0 else None
                    box=self.presence.track(frame.bgr,text,current['bbox'],epoch,
                                             decision,session,color,frame.seq,
                                             frame.stamp,center=crop['center'],
                                             side=side,max_growth=2.2,
                                             alt_center=alt)
                    kind='track'
                else:
                    box=self.presence.acquire(frame.bgr,text,epoch,decision,
                                               session,color,frame.seq,frame.stamp)
                    kind='acquire'
                if not self.active(epoch):
                    raise StageInactive()
                with self.lock:
                    if self.epoch==epoch:
                        self.pending=(epoch,frame,box,decision,kind)
                self.audit(kind='decision',decision=decision,session=session,color=color,
                           bbox=box,mode=kind,model_box=box,
                           model_track_present=bool(current),
                           model_track_age_s=(time.monotonic()-current['source_acquired']
                                              if current and 'source_acquired' in current else None),
                           source_frame=frame.seq,source_stamp=frame.stamp,
                           source_age_s=time.monotonic()-frame.acquired,
                           latency_s=time.monotonic()-start,
                           semantic_age_s=(time.monotonic()-current['source_acquired']
                                           if current and 'source_acquired' in current else None))
                rospy.loginfo('MULTIMODAL_DECISION_V2 id=%s session=%s color=%s mode=%s bbox=%s age=%.3f',
                              decision,session,color,kind,box,
                              time.monotonic()-frame.acquired)
            except StageInactive:
                self.audit(kind='discard_inactive',decision=decision,session=session)
            except Exception as exc:
                self.audit(kind='inference_error',decision=decision,session=session,
                           error=repr(exc))
                rospy.logerr('MULTIMODAL_INFERENCE_ERROR %s',exc)

    def tracking_loop(self):
        last_epoch=-1
        last_published=-1
        while not self.stop_event.wait(0.005):
            now=time.monotonic()
            with self.lock:
                epoch,session,color=self.epoch,self.session,self.color
                frames=list(self.frames)
                pending=self.pending
            if epoch!=last_epoch:
                self.tracker.reset()
                self.model_track=None
                self.track_misses=0
                last_epoch=epoch
                last_published=-1
            if session is None or not frames:
                continue
            if pending and pending[0]==epoch:
                _,source,box,decision,kind=pending
                if box is not None:
                    self.est.measure(box,source.acquired,decision,source.seq)
                    self.audit(kind='v6_measure',session=session,decision=decision,
                               source_frame=source.seq,mode=kind,bbox=list(box),
                               age_s=time.monotonic()-source.acquired,
                               yaw=self.est.poses[-1][4] if self.est.poses else None)
                else:
                    self.audit(kind='v6_no_measure',session=session,decision=decision,
                               source_frame=source.seq,mode=kind,
                               age_s=time.monotonic()-source.acquired,
                               hold_age_s=(time.monotonic()-self.est.meas['acquired'])
                               if self.est.meas is not None else None)
                with self.lock:
                    if self.pending is pending:
                        self.pending=None
            model_current=self.est.view()
            publish_current=self.est.publish(time.monotonic())
            with self.lock:
                if epoch!=self.epoch or session!=self.session:
                    continue
                self.model_track=model_current
                self.current=publish_current
                self.latest_display=(frames[-1],publish_current,color,session,
                                     'v6' if publish_current else 'v6_lost')
            if frames[-1].seq==last_published:
                continue
            last_published=frames[-1].seq
            now_pub=time.monotonic()
            # v6: the estimator already produces the carried box and its
            # confidence, so the old guard (which re-held a stale box and
            # altitude-climbed by moving the box) is out of the path.
            guarded=(dict(bbox=tuple(publish_current['bbox']),
                          score=float(publish_current['score']),
                          mode=publish_current['mode'],
                          age_s=publish_current['age_s'],
                          note='v6')
                     if publish_current is not None else None)
            objects=Objects()
            if guarded is not None:
                # Fresh as of this publication; the model age travels in the
                # audit fields instead of being hidden inside the stamp.
                stamp=rospy.Time.now().to_sec()
                decision=publish_current['decision'] if publish_current else 'guard'
            else:
                stamp=publish_current['stamp'] if publish_current else frames[-1].stamp
                decision=publish_current['decision'] if publish_current else 'invalid'
            objects.header.stamp=rospy.Time.from_sec(stamp)
            objects.header.frame_id=f'fm9g:{session}:{decision}'
            # Publish sequence, not measurement sequence: the C++ node averages
            # the last filter_window_size distinct seq values, so reusing the
            # measurement seq would average boxes that are seconds apart.
            objects.header.seq=frames[-1].seq
            objects.source_id=1
            if guarded is not None:
                x1,y1,x2,y2=[int(round(v)) for v in guarded['bbox']]
                obj=Obj()
                obj.header=objects.header
                obj.class_name=color+'_balloon'
                obj.score=float(guarded['score'])
                obj.left_top_x,obj.left_top_y,obj.right_bottom_x,obj.right_bottom_y=x1,y1,x2,y2
                obj.center_x,obj.center_y=round((x1+x2)/2),round((y1+y2)/2)
                objects.objects=[obj]
            camera_seq=publish_current['seq'] if publish_current else frames[-1].seq
            self.objects_pub.publish(objects)
            self.audit(kind='publish',session=session,decision=decision,
                       frame_seq=camera_seq,publication_seq=objects.header.seq,
                       stamp=stamp,bbox=guarded['bbox'] if guarded else None,
                       raw_tracker_bbox=publish_current['meas_bbox'] if publish_current else None,
                       visible_fraction=None,
                       semantic_age_s=publish_current['semantic_age_s']
                       if publish_current else None,
                       model_track_age_s=model_current['semantic_age_s']
                       if model_current else None,
                       suppressed_by_negative=bool(self.track_misses),
                       reason=self.tracker.reason,
                       guard_mode=guarded['mode'] if guarded else None,
                       guard_age_s=guarded['age_s'] if guarded else None,
                       guard_note=guarded['note'] if guarded else None,
                       guard_score=guarded['score'] if guarded else None,
                       odom_z=self.odom_z)
            if guarded is not None:
                rospy.loginfo_throttle(
                    0.2,
                    'MULTIMODAL_PIXEL session=%s source=%s stamp=%.6f age=%.3f model_age=%.3f center=(%.1f,%.1f) size=(%.1f,%.1f) guard=%s',
                    session,objects.header.frame_id,stamp,
                    publish_current['semantic_age_s'] if publish_current else 0.0,
                    model_current['semantic_age_s'] if model_current else -1.0,
                    guarded['bbox'][0]+(guarded['bbox'][2]-guarded['bbox'][0])/2,
                    guarded['bbox'][1]+(guarded['bbox'][3]-guarded['bbox'][1])/2,
                    guarded['bbox'][2]-guarded['bbox'][0],
                    guarded['bbox'][3]-guarded['bbox'][1],
                    guarded['mode'])

    def refresh_window(self):
        # Called exclusively by mission_once's MAIN thread.
        with self.lock:
            display=self.latest_display if self.session else None
            latest=self.frames[-1] if self.frames else None
            active=self.session is not None
        if display:
            frame,current,color,session,reason=display
            image=frame.bgr.copy()
            if current:
                x1,y1,x2,y2=[int(round(v)) for v in current['bbox']]
                cv2.rectangle(image,(x1,y1),(x2,y2),(0,255,0),2)
                line=f"{color} FM9G {current['decision']} age={current['semantic_age_s']:.2f}s"
            else: line=f'{color}: waiting/invalid ({reason})'
            cv2.putText(image,line,(8,22),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,255,255),1)
            cv2.putText(image,f'frame={frame.seq} stamp={frame.stamp:.3f} session={session}',
                        (8,44),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,255,255),1)
            cv2.imshow(self.window_name,image)
            message=Image()
            message.header.stamp=rospy.Time.from_sec(frame.stamp)
            message.height,message.width=image.shape[:2]
            message.encoding='bgr8';message.step=message.width*3;message.data=image.tobytes()
            self.debug_pub.publish(message)
            if active and time.monotonic()-self.last_snapshot>=1.0:
                target=self.output/'window'/f'{frame.seq:08d}.jpg'
                cv2.imwrite(str(target),image)
                self.audit(kind='window_frame',frame_seq=frame.seq,image=str(target.relative_to(self.output)),
                           sha256=hashlib.sha256(target.read_bytes()).hexdigest(),session=session)
                self.last_snapshot=time.monotonic()
        elif latest:
            image=latest.bgr.copy()
            cv2.putText(image,'FM9G inactive - sensor1 RGB',(8,22),cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,(0,255,255),1)
            cv2.imshow(self.window_name,image)
        cv2.waitKey(1)

    def close(self):
        self.stop_event.set()
        for subscriber in self.subs: subscriber.unregister()
        with self.lock:
            self.epoch+=1
            self.session=self.color=None
        for worker in self.workers: worker.join(timeout=15)
        gate=DetEnable();gate.is_open=True;self.det_gate.publish(gate)
        self.audit(kind='closed',workers_alive=[w.name for w in self.workers if w.is_alive()])
        cv2.destroyAllWindows()
