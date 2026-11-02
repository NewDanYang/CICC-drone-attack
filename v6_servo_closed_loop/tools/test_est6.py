import sys
sys.path.insert(0, '.scratch/v6')
from estimator_v6 import TargetEstimator
est = TargetEstimator(audit=lambda **kw: None)
est.reset(1)
# 10 Hz odom along the same segment
for i in range(13):
    t = i * 0.1
    x = 3.769 - 0.27 * t
    y = -2.353 - 0.13 * t
    est.on_pose(t, x, y, 0.39, -1.23)
est.measure([298.4, 216.3, 347.3, 255.9], 0.00, decision='a', seq=1)
est.measure([254.0, 235.0, 315.0, 302.0], 0.60, decision='b', seq=2)
print('range', round(est.range_m, 3), 'cx_eff', round(est.cx_eff, 1))
for t in (0.6, 0.8, 1.0, 1.2):
    b = est.predict(t)
    print('t=%.1f cx=%.0f  size=%.0fx%.0f' % (t, (b[0]+b[2])/2, b[2]-b[0], b[3]-b[1]))