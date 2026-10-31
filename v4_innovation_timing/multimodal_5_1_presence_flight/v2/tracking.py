"""Non-semantic, scale-adaptive tracking with timestamped frame replay."""
from dataclasses import dataclass
import math


@dataclass
class Frame:
    seq: int
    stamp: float
    acquired: float
    bgr: object


class ReplayTracker:
    def __init__(self, cv2, max_semantic_age=8.0, max_gap=0.5):
        self.cv2=cv2
        self.max_semantic_age=max_semantic_age
        self.max_gap=max_gap
        self.reset()

    def reset(self):
        self.tracker=None
        self.box=None
        self.raw_box=None
        self.visible_fraction=None
        self.frame=None
        self.source=None
        self.decision=None
        self.track_id=None
        self.reason='not_initialized'

    def invalidate(self,reason):
        self.reset()
        self.reason=reason

    @staticmethod
    def valid_box(box,size):
        x1,y1,x2,y2=box
        width,height=size
        return (all(math.isfinite(v) for v in box) and 0<=x1<x2<=width
                and 0<=y1<y2<=height and x2-x1>=4 and y2-y1>=4)

    def initialize(self,source,box,decision,now):
        self.reset()
        if now-source.acquired>self.max_semantic_age or now<source.acquired:
            self.reason='semantic_expired_before_initialization'
            return False
        height,width=source.bgr.shape[:2]
        if not self.valid_box(box,(width,height)):
            self.reason='invalid_model_box'
            return False
        x1,y1,x2,y2=[int(round(v)) for v in box]
        self.tracker=self.cv2.TrackerCSRT_create()
        self.tracker.init(source.bgr,(x1,y1,x2-x1,y2-y1))
        self.box=list(box)
        self.raw_box=list(box)
        self.visible_fraction=1.0
        self.frame=self.source=source
        self.decision=decision
        self.track_id=decision
        self.reason=None
        return True

    def update(self,frame,now):
        if self.tracker is None:
            return False
        if now-self.source.acquired>self.max_semantic_age:
            self.invalidate('semantic_expired')
            return False
        if frame.seq<=self.frame.seq:
            return self.box is not None
        gap=frame.acquired-self.frame.acquired
        stamp_gap=frame.stamp-self.frame.stamp
        if gap<=0 or gap>self.max_gap or stamp_gap<0 or stamp_gap>self.max_gap:
            self.invalidate('frame_gap_or_clock_jump')
            return False
        okay,xywh=self.tracker.update(frame.bgr)
        x,y,width,height=xywh
        image_height,image_width=frame.bgr.shape[:2]
        if not okay:
            self.invalidate('tracker_response_lost')
            return False
        raw_box=[x,y,x+width,y+height]
        if not all(math.isfinite(v) for v in raw_box) or width<=0 or height<=0:
            self.invalidate('tracker_invalid_geometry')
            return False
        box=[max(0,x),max(0,y),min(image_width,x+width),min(image_height,y+height)]
        visible_fraction=max(0,box[2]-box[0])*max(0,box[3]-box[1])/(width*height)
        if visible_fraction<.25 or not self.valid_box(box,(image_width,image_height)):
            self.invalidate('tracker_left_image')
            return False
        self.box=box
        self.raw_box=raw_box
        self.visible_fraction=visible_fraction
        self.frame=frame
        return True

    def replay(self,frames,now):
        for frame in frames:
            if not self.update(frame,now):
                return False
        return self.box is not None

    def current(self,now,max_frame_age=0.35,max_model_age=None):
        if self.frame is None:
            return None
        if now-self.source.acquired>self.max_semantic_age:
            self.invalidate('semantic_expired')
            return None
        if max_model_age is not None and now-self.source.acquired>max_model_age:
            return None
        if now-self.frame.acquired>max_frame_age:
            return None
        return {'bbox':list(self.box),'stamp':self.frame.stamp,'seq':self.frame.seq,
                'decision':self.decision,'track_id':self.track_id,
                'semantic_age_s':now-self.source.acquired,'raw_bbox':list(self.raw_box),
                'source_acquired':self.source.acquired,
                'visible_fraction':self.visible_fraction}

    def confirm(self,source,decision,track_id,now):
        if (self.tracker is None or self.track_id!=track_id or
                now-source.acquired>self.max_semantic_age or source.acquired<self.source.acquired):
            return False
        # This is a NEW semantic observation of the tracked object's crop.
        # Preserve the tracked geometry; do not reset to an old frame/bbox.
        self.source=source
        self.decision=decision
        return True
