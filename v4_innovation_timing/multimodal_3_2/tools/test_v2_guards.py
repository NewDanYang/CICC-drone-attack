"""Regression guards for stale frames, scale propagation and stage cancellation."""
import json
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from v2.tracking import Frame, ReplayTracker


class Pixels:
    shape=(480,640,3)


class TrackerStub:
    def init(self,image,box): pass
    def update(self,image): return True,(200,100,80,100)


class CvStub:
    @staticmethod
    def TrackerCSRT_create(): return TrackerStub()


class FrameGuards(unittest.TestCase):
    def test_partial_backend_match_is_clipped_without_freshening_timestamp(self):
        class EdgeTracker(TrackerStub):
            def update(self,image):return True,(-5,100,50,60)
        class EdgeCv:
            TrackerCSRT_create=staticmethod(EdgeTracker)
        tracker=ReplayTracker(EdgeCv)
        self.assertTrue(tracker.initialize(Frame(1,100,1,Pixels()),[0,100,45,160],'d',1.1))
        self.assertTrue(tracker.update(Frame(2,100.1,1.1,Pixels()),1.2))
        current=tracker.current(1.2)
        self.assertEqual(current['bbox'],[0,100,45,160])
        self.assertEqual(current['raw_bbox'],[-5,100,45,160])
        self.assertAlmostEqual(current['visible_fraction'],.9)
        self.assertEqual(current['stamp'],100.1)

    def test_backend_match_completely_outside_image_is_invalid(self):
        class OutsideTracker(TrackerStub):
            def update(self,image):return True,(-100,100,50,60)
        class OutsideCv:
            TrackerCSRT_create=staticmethod(OutsideTracker)
        tracker=ReplayTracker(OutsideCv)
        self.assertTrue(tracker.initialize(Frame(1,100,1,Pixels()),[0,100,45,160],'d',1.1))
        self.assertFalse(tracker.update(Frame(2,100.1,1.1,Pixels()),1.2))
        self.assertIsNone(tracker.current(1.2))
        self.assertEqual(tracker.reason,'tracker_left_image')

    def test_model_result_age_starts_at_source_capture(self):
        tracker=ReplayTracker(CvStub,max_semantic_age=8)
        source=Frame(1,101,1.0,Pixels())
        self.assertFalse(tracker.initialize(source,[210,110,250,160],'decision',10.0))
        self.assertIsNone(tracker.current(10.0))

    def test_replay_preserves_actual_frame_stamp_and_scale(self):
        tracker=ReplayTracker(CvStub,max_semantic_age=8)
        source=Frame(1,101,1.0,Pixels())
        self.assertTrue(tracker.initialize(source,[210,110,250,160],'decision',1.1))
        self.assertTrue(tracker.update(Frame(2,101.1,1.1,Pixels()),1.2))
        current=tracker.current(1.2)
        self.assertEqual(current['stamp'],101.1)
        self.assertEqual(current['bbox'],[200,100,280,200])
        self.assertAlmostEqual(current['semantic_age_s'],0.2)

    def test_gap_and_lost_track_never_republish_old_box(self):
        tracker=ReplayTracker(CvStub)
        self.assertTrue(tracker.initialize(Frame(1,100,1,Pixels()),[200,100,240,150],'d',1.1))
        self.assertFalse(tracker.update(Frame(8,101,2,Pixels()),2.1))
        self.assertIsNone(tracker.current(2.1))

    def test_no_fresh_pixel_from_old_observation(self):
        tracker=ReplayTracker(CvStub)
        self.assertTrue(tracker.initialize(Frame(1,100,1,Pixels()),[200,100,240,150],'d',1.1))
        self.assertIsNone(tracker.current(1.8))


class GateGuards(unittest.TestCase):
    def test_duplicate_start_and_late_result_after_stop(self):
        from v2.runtime import PerceptionBridge
        from std_msgs.msg import String
        class Publisher:
            def publish(self,msg): pass
        bridge=PerceptionBridge.__new__(PerceptionBridge)
        bridge.lock=threading.RLock();bridge.stop_event=threading.Event()
        bridge.epoch=0;bridge.session=bridge.color=None
        bridge.det_gate=Publisher();bridge.audit=lambda **kwargs: None
        start=String(data=json.dumps({'action':'start','session':'one','color':'blue'}))
        bridge.on_gate(start)
        old_epoch=bridge.epoch
        bridge.current={'bbox':[1,2,3,4]}
        bridge.on_gate(start)
        self.assertEqual(bridge.epoch,old_epoch)
        self.assertIsNotNone(bridge.current)
        bridge.on_gate(String(data=json.dumps({'action':'stop','session':'one'})))
        self.assertFalse(bridge.active(old_epoch))
        self.assertIsNone(bridge.current)
        bridge.on_gate(String(data=json.dumps({'action':'start','session':'two','color':'red'})))
        self.assertFalse(bridge.active(old_epoch))
        bridge.on_gate(String(data=json.dumps({'action':'stop','session':'one'})))
        self.assertEqual(bridge.session,'two')

    def test_rgb_and_alpha_byte_order(self):
        from v2.runtime import decode_bgr
        from types import SimpleNamespace
        msg=SimpleNamespace(encoding='rgba8',width=1,height=1,step=8,
                            data=bytes([11,22,33,255,0,0,0,0]))
        self.assertEqual(decode_bgr(msg).tolist(),[[[33,22,11]]])


class SemanticGeometryGuards(unittest.TestCase):
    def test_presence_is_clarified_by_model_without_guessing_mission_color(self):
        from v2.localizer import semantic_labels
        replies=iter([['是的，有一个气球。','这张图片中没有气球。','blue balloon','有一只气球。'],
                      ['purple','none']])
        sizes=[]
        def infer(images,prompt): sizes.append(len(images));return next(replies)
        labels,_=semantic_labels([object() for _ in range(4)],infer)
        self.assertEqual(labels,['purple',None,'blue',None])
        self.assertEqual(sizes,[4,2])

    def test_color_clarification_rejects_negative_uncertain_or_multiple_colors(self):
        from v2.localizer import affirmative_presence,parse_color_reply
        self.assertTrue(affirmative_presence('是的，这张图片中有气球。'))
        self.assertFalse(affirmative_presence('这张图片中没有气球。'))
        self.assertEqual(parse_color_reply('图中气球是紫色的。'),'purple')
        for answer in ('可能是红色','红色或蓝色','没有红色气球'):
            with self.assertRaises(ValueError):parse_color_reply(answer)

    def test_geometry_uses_only_model_positive_windows(self):
        from PIL import Image
        from v2.localizer import OverlapLocalizer
        def infer(images,prompt):
            self.assertEqual(len(images),16)
            return ['red balloon' if i in (5,6,9,10) else 'no balloon' for i in range(16)]
        image=Image.new('RGB',(640,480)) # Contract test, not a vision accuracy sample.
        self.assertEqual(OverlapLocalizer(infer).locate(image,'red'),[128,96,512,384])
        self.assertIsNone(OverlapLocalizer(infer).locate(image,'blue'))

    def test_inconsistent_or_empty_semantics_never_guess_box(self):
        from PIL import Image
        from v2.localizer import OverlapLocalizer
        image=Image.new('RGB',(640,480))
        inconsistent=lambda *_:['red balloon' if i in (0,15) else 'no balloon' for i in range(16)]
        self.assertIsNone(OverlapLocalizer(inconsistent).locate(image,'red'))
        self.assertIsNone(OverlapLocalizer(lambda *_:['unparseable']*16).locate(image,'red'))

    def test_regions_without_model_area_cannot_search_whole_frame(self):
        from v2.geometry import local_regions
        import numpy as np
        pixels=np.zeros((480,640,3),np.uint8)
        self.assertEqual(local_regions(pixels,None),([],[]))
        self.assertEqual(local_regions(pixels,[0,0,640,480]),([],[]))

    def test_only_model_confirmed_adjacent_regions_form_selected_box(self):
        from v2.geometry import model_selected_box
        regions=[dict(region=1,bbox=[10,10,30,30],area=300),
                 dict(region=2,bbox=[10,30,30,40],area=150),
                 dict(region=3,bbox=[80,10,100,30],area=350)]
        self.assertEqual(model_selected_box(regions,[[1,2]],['purple','purple','blue'],'purple'),[10,10,30,40])
        self.assertIsNone(model_selected_box(regions,[[1,2]],['blue',None,'blue'],'purple'))


if __name__=='__main__': unittest.main(verbosity=2)
