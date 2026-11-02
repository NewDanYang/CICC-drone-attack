import sys, math
sys.path.insert(0, r'D:\CICC-drone-attack\.scratch\v7')
from v6_estimator import TargetEstimator
e = TargetEstimator()
def m(acquired, bbox, yaw):
    e.on_pose(acquired, 4.2, -2.1, 0.7, yaw)
    e.measure(bbox, acquired, 'd', 1)
m(0.0, [276.6, 224.8, 309.6, 255.2], -1.51)
m(0.6, [286.0, 224.8, 312.0, 255.2], -1.48)
print('velocity', [round(v, 2) for v in e._velocity()], 'growth', round(e._growth(), 3))
for age in (0.0, 0.3, 0.6, 0.9, 1.2):
    p = e.predict(0.6 + age)
    print('age', age, 'cx', round((p[0]+p[2])/2, 1), 'w', round(p[2]-p[0], 1))
print('alt_center', [round(v, 1) for v in e.measured_center()])
c = e.crop_params(0.9)
print('crop center', [round(v, 1) for v in c['center']], 'side', round(c['side'], 1), 'alt', [round(v, 1) for v in c['alt_center']])
p = e.publish(1.25)
print('publish mode', p['mode'], 'score', round(p['score'], 2), 'arrival_age', round(p['arrival_age_s'], 2))