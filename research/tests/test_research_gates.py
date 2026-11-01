import unittest
from depth.planner_boundary import PlannerBoundary
from depth.recovery_watchdog import RecoveryWatchdog
from depth.validator import Extrinsic,pair,transform
from timing.retiming import Curve,Segment,validate
class GateTests(unittest.TestCase):
 def test_boundary(self):
  g=PlannerBoundary('sensor'); self.assertTrue(g.accept({'frame_id':'sensor','stamp':10,'points':[(1,2,3)]},10.1)['research_only']); self.assertIsNone(g.accept({'frame_id':'map','stamp':10,'points':[(1,2,3)]},10.1))
 def test_reset_and_stale(self):
  g=PlannerBoundary('sensor'); self.assertIsNotNone(g.accept({'frame_id':'sensor','stamp':10,'points':[(1,2,3)]},10)); self.assertIsNone(g.accept({'frame_id':'sensor','stamp':9,'points':[(1,2,3)]},9.5)); self.assertEqual(g.epoch,1)
 def test_pair_interpolate_and_transform(self):
  p=pair({'stamp':1.05},[{'stamp':1,'position':[0,0,0],'quaternion':[0,0,0,1],'parent_frame':'world','child_frame':'body'},{'stamp':1.1,'position':[0,0,0],'quaternion':[0,0,0,1],'parent_frame':'world','child_frame':'body'}],1.1); self.assertEqual(transform([(1,0,0)],p,Extrinsic(((1,0,0),(0,1,0),(0,0,1)),(.2,0,0))),[(1.2,0,0)])
 def test_watchdog_fail_closed(self):
  w=RecoveryWatchdog(); e={'kind':'sample','mono':2,'command_receive_mono':1,'odom_receive_mono':1.9,'state_receive_mono':1.9,'connected':True,'armed':False,'mode':'AUTO.LOITER','command_header_ros':2}; self.assertEqual(w.evaluate(e)['phase'],'ABORTED')
 def test_timing_checks_acceleration_and_jerk(self):
  c=Curve([Segment([(0,0,0),(0,0,0),(1,0,0),(1,0,0)],1.)])
  self.assertEqual(validate(c,(10,.5,4.)),'acceleration_bound')
  self.assertEqual(validate(c,(10,10,1.)),'jerk_bound')
 def test_no_flight_publication(self):
  from timing.retiming import publication_gate
  self.assertFalse(publication_gate()['publish'])
if __name__=='__main__':unittest.main()
