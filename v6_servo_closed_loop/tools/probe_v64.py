import sys
sys.path.insert(0, '/home/ubuntu/model')
from fm9g_perception.runtime import PerceptionBridge
from fm9g_perception.v6_estimator import TargetEstimator
from fm9g_perception import presence
e = TargetEstimator()
print('IMPORT_OK carry_max', e.CARRY_MAX, 'cx_eff', e.cx_eff, 'grow_factors', presence.NativePresenceSweep.__init__.__defaults__)
print('track args', presence.NativePresenceSweep.track.__code__.co_varnames[:12])
sweep = presence.NativePresenceSweep.__dict__.get('grow_factors', 'class-level missing')
print('grow attr', sweep)