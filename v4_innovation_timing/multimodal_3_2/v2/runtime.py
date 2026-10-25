"""Same-process FM9G perception bridge; this module never commands flight."""
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
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

from .localizer import OverlapLocalizer, expand, semantic_labels
from .geometry import local_regions,model_selected_box
from .tracking import Frame, ReplayTracker


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
        self.latest_display=None
        self.tracker=ReplayTracker(cv2,max_semantic_age=12.0)
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
        self.objects_pub=rospy.Publisher('/multimodal/objects',Objects,queue_size=1)
        self.debug_pub=rospy.Publisher('/multimodal/debug_image',Image,queue_size=1)
        self.det_gate=rospy.Publisher('/detect_ctrl',DetEnable,queue_size=2,latch=True)
        self.image_topic='/rflysim/sensor1/img_rgb'
        self.subs=[rospy.Subscriber(self.image_topic,Image,self.on_image,queue_size=1,buff_size=4*1024*1024),
                   rospy.Subscriber('/multimodal/balloon_target',String,self.on_gate,queue_size=5),
                   rospy.Subscriber('/mission_result',String,self.on_result,queue_size=2)]
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
                self.last_inference_seq=-1
            gate=DetEnable(); gate.is_open=action!='start'
            self.det_gate.publish(gate)
            self.audit(kind='gate',action=action,session=session,color=color,epoch=self.epoch,
                       yolo_enabled=gate.is_open)
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
                if self.session is None or not self.frames: continue
                frame=self.frames[-1]
                epoch,session,color=self.epoch,self.session,self.color
                current=self.current.copy() if self.current else None
                if current:
                    matched=next((f for f in reversed(self.frames) if f.seq==current['seq']),None)
                    if matched: frame=matched
                    else: current=None
                if frame.seq==self.last_inference_seq: continue
                self.last_inference_seq=frame.seq
            decision=uuid.uuid4().hex[:12]
            image=PILImage.fromarray(cv2.cvtColor(frame.bgr,cv2.COLOR_BGR2RGB))
            image_path=self.output/'images'/(decision+'.png')
            image.save(image_path)
            self.audit(kind='model_source',decision=decision,session=session,color=color,
                       frame_seq=frame.seq,stamp=frame.stamp,acquired=frame.acquired,
                       image=str(image_path.relative_to(self.output)),
                       image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                       pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(),size=image.size)
            def infer(images,prompt):
                if not self.active(epoch): raise StageInactive()
                start=time.monotonic()
                with self.model_lock,torch.inference_mode():
                    if not self.active(epoch): raise StageInactive()
                    answers=self.model.chat(image=None,
                        msgs=[[{'role':'user','content':[im,prompt]}] for im in images],
                        tokenizer=self.tokenizer,processor=self.processor,sampling=False,stream=False,
                        num_beams=1,max_new_tokens=12,max_slice_nums=1)
                if not self.active(epoch): raise StageInactive()
                if isinstance(answers,str): answers=[answers]
                self.audit(kind='model_call',decision=decision,session=session,batch_size=len(images),
                           answers=answers,prompt=prompt,latency_s=time.monotonic()-start,
                           image_sizes=[im.size for im in images],
                           image_pixels_sha256=[hashlib.sha256(im.tobytes()).hexdigest() for im in images])
                return answers
            start=time.monotonic()
            try:
                if current:
                    roi=expand(current['bbox'],0.35,image.size)
                    labels,_=semantic_labels([image.crop(roi)],infer,
                        lambda **event:self.audit(decision=decision,session=session,**event))
                    confirmed=labels[0]==color
                    box=current['bbox'] if confirmed else None
                    model_box=None
                    kind='confirmation'
                else:
                    model_box=OverlapLocalizer(infer,lambda **event: self.audit(decision=decision,session=session,**event)).locate(
                        image,color)
                    candidates,adjacency=local_regions(frame.bgr,model_box)
                    candidate_images=[PILImage.fromarray(cv2.cvtColor(row.pop('_pixels_bgr'),cv2.COLOR_BGR2RGB))
                                      for row in candidates]
                    candidate_files=[]
                    for index,candidate_image in enumerate(candidate_images):
                        path=self.output/'images'/f'{decision}_region_{index:02d}.png'
                        candidate_image.save(path)
                        candidate_files.append(dict(image=str(path.relative_to(self.output)),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                    if candidates:
                        labels,_=semantic_labels(candidate_images,infer,
                            lambda **event:self.audit(decision=decision,session=session,**event))
                    else:labels=[]
                    box=model_selected_box(candidates,adjacency,labels,color)
                    self.audit(kind='geometry_candidates',decision=decision,session=session,
                               model_roi=model_box,candidates=candidates,adjacency=adjacency,
                               model_labels=labels,bbox=box,candidate_images=candidate_files,
                               input_mode='original_region_pixels_with_other_regions_blacked_out')
                    kind='initialization'
                if not self.active(epoch): raise StageInactive()
                with self.lock:
                    if self.epoch==epoch:
                        self.pending=(epoch,frame,box,decision,kind,current['track_id'] if current else None)
                self.audit(kind='decision',decision=decision,session=session,color=color,bbox=box,
                           mode=kind,model_box=model_box,verification_roi=roi if current else None,
                           source_frame=frame.seq,source_stamp=frame.stamp,
                           source_age_s=time.monotonic()-frame.acquired,latency_s=time.monotonic()-start)
                rospy.loginfo('MULTIMODAL_DECISION_V2 id=%s session=%s color=%s bbox=%s age=%.3f',
                              decision,session,color,box,time.monotonic()-frame.acquired)
            except StageInactive:
                self.audit(kind='discard_inactive',decision=decision,session=session)
            except Exception as exc:
                self.audit(kind='inference_error',decision=decision,session=session,error=repr(exc))
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
                self.pending=None
            if epoch!=last_epoch:
                self.tracker.reset()
                last_epoch=epoch
                last_published=-1
            if session is None or not frames: continue
            if pending and pending[0]==epoch:
                _,source,box,decision,kind,track_id=pending
                if kind=='initialization' and self.tracker.current(now) is not None:
                    self.audit(kind='discard_superseded_initialization',session=session,decision=decision)
                elif kind=='confirmation' and self.tracker.track_id!=track_id:
                    self.audit(kind='discard_superseded_confirmation',session=session,decision=decision)
                elif box is None:
                    self.tracker.invalidate('model_reports_no_target')
                elif kind=='confirmation':
                    self.tracker.confirm(source,decision,track_id,now)
                elif self.tracker.initialize(source,box,decision,now):
                    self.tracker.replay([f for f in frames if f.seq>source.seq],time.monotonic())
                    self.audit(kind='replay',session=session,decision=decision,
                               from_seq=source.seq,to_seq=frames[-1].seq,reason=self.tracker.reason)
            elif self.tracker.frame:
                self.tracker.replay([f for f in frames if f.seq>self.tracker.frame.seq],now)
            current=self.tracker.current(time.monotonic())
            with self.lock:
                if epoch!=self.epoch or session!=self.session: continue
                self.current=current
                display_frame=self.tracker.frame if current else frames[-1]
                self.latest_display=(display_frame,current,color,session,self.tracker.reason)
            if frames[-1].seq==last_published: continue
            last_published=frames[-1].seq
            objects=Objects()
            stamp=current['stamp'] if current else frames[-1].stamp
            decision=current['decision'] if current else 'invalid'
            objects.header.stamp=rospy.Time.from_sec(stamp)
            objects.header.frame_id=f'fm9g:{session}:{decision}'
            objects.header.seq=current['seq'] if current else frames[-1].seq
            objects.source_id=1
            if current:
                x1,y1,x2,y2=[int(round(v)) for v in current['bbox']]
                obj=Obj(); obj.header=objects.header
                obj.class_name=color+'_balloon'; obj.score=1.0
                obj.left_top_x,obj.left_top_y,obj.right_bottom_x,obj.right_bottom_y=x1,y1,x2,y2
                obj.center_x,obj.center_y=round((x1+x2)/2),round((y1+y2)/2)
                objects.objects=[obj]
            camera_seq=current['seq'] if current else frames[-1].seq
            self.objects_pub.publish(objects) # rospy rewrites header.seq as publication sequence.
            self.audit(kind='publish',session=session,decision=decision,frame_seq=camera_seq,
                       publication_seq=objects.header.seq,
                       stamp=stamp,bbox=current['bbox'] if current else None,
                       raw_tracker_bbox=current['raw_bbox'] if current else None,
                       visible_fraction=current['visible_fraction'] if current else None,
                       semantic_age_s=current['semantic_age_s'] if current else None,
                       reason=self.tracker.reason)

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
