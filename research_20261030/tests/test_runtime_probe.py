"""Fixture parser tests, not evidence that a server probe was executed."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime_probe import parse_project_mappings

class ProbeTest(unittest.TestCase):
    def test_replaced_plugin_keeps_mapped_identity(self):
        text='''7f00-7f10 r--p 00000000 08:01 123 /home/ubuntu/catkin_ws/devel/lib/libvisual_servo.so (deleted)
7f10-7f20 r-xp 00001000 08:01 123 /home/ubuntu/catkin_ws/devel/lib/libvisual_servo.so (deleted)
8f00-8f10 r-xp 00000000 08:01 789 /home/ubuntu/new ws/devel/lib/libvisual_servo.so
9f00-9f10 r-xp 00000000 08:01 456 /usr/lib/libc.so.6
af00-af10 rw-p 00000000 00:00 0 [heap]
'''
        rows=parse_project_mappings(text)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['inode'],123)
        self.assertTrue(rows[0]['deleted'])
        self.assertEqual(rows[0]['mapping'],'7f00-7f10')
        self.assertFalse(rows[1]['deleted'])
        self.assertIn('new ws',rows[1]['path'])

if __name__=='__main__':unittest.main()
