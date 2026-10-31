import os
from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mission_contract import full_mission_problems
from patch_mission_contract import patched

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.old=os.environ.get('MISSION_REQUIRE_FULL_SEQUENCE')
        os.environ['MISSION_REQUIRE_FULL_SEQUENCE']='1'
    def tearDown(self):
        if self.old is None:os.environ.pop('MISSION_REQUIRE_FULL_SEQUENCE',None)
        else:os.environ['MISSION_REQUIRE_FULL_SEQUENCE']=self.old
    def test_each_color(self):
        for color in ('red','purple','blue'):
            self.assertEqual([],full_mission_problems('takeoff\ncross_frame\ndetect_aruco\nreturn_cross_frame\nhit_balloon:'+color+'\nland'))
    def test_missing_first_cross(self):
        self.assertTrue(full_mission_problems('takeoff\ndetect_aruco\nreturn_cross_frame\nhit_balloon:red\nland'))
    def test_four_stage_local_script(self):
        self.assertTrue(full_mission_problems('takeoff\ndetect_aruco\nhit_balloon:blue\nland'))
    def test_duplicate_and_wrong_order(self):
        for lines in ('takeoff\ntakeoff\ncross_frame\ndetect_aruco\nreturn_cross_frame\nhit_balloon:red\nland',
                      'takeoff\ndetect_aruco\ncross_frame\nreturn_cross_frame\nhit_balloon:red\nland'):
            self.assertTrue(full_mission_problems(lines))
    def test_unknown_empty(self):
        for value in ('',None,'start_all','takeoff\ncross_frame\ndetect_aruco\nreturn_cross_frame\nhit_balloon:green\nland'):
            self.assertTrue(full_mission_problems(value))
    def test_partial_request_unaffected(self):
        os.environ['MISSION_REQUIRE_FULL_SEQUENCE']='0'
        self.assertEqual([],full_mission_problems('takeoff'))
    def test_real_source_retry_no_invalid_fallback(self):
        source=ROOT.parent/'v3_stability/rule_compliance/deploy/mission_once.py'
        data=patched(source.read_bytes())
        # Stub imports only. Preserve real validation/retry code; no ROS/model calls.
        names=('torch','transformers','rospy','std_msgs','std_msgs.msg')
        saved={k:sys.modules.get(k) for k in names}
        try:
            for name in names:sys.modules[name]=types.ModuleType(name)
            sys.modules['transformers'].AutoModel=object
            sys.modules['transformers'].AutoTokenizer=object
            sys.modules['std_msgs.msg'].String=object
            ns={'__name__':'contract_test'};exec(compile(data,str(source),'exec'),ns)
            bad='takeoff\ndetect_aruco\nreturn_cross_frame\nhit_balloon:red\nland'
            good='takeoff\ncross_frame\ndetect_aruco\nreturn_cross_frame\nhit_balloon:red\nland'
            replies=iter([bad,good]);ns['generate_commands']=lambda *args:next(replies)
            self.assertEqual(good,ns['generate_validated_commands'](None,None,[], '起飞，穿框，识别二维码，穿回来，打红色气球，降落'))
            ns['generate_commands']=lambda *args:bad
            self.assertIsNone(ns['generate_validated_commands'](None,None,[], '起飞，穿框，识别二维码，穿回来，打红色气球，降落'))
        finally:
            for k,v in saved.items():
                if v is None:sys.modules.pop(k,None)
                else:sys.modules[k]=v
    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):patched(b'import sys\n')

if __name__=='__main__':unittest.main()
