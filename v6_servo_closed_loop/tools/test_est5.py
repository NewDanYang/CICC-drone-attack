import sys
sys.path.insert(0, '.scratch/v6')
from estimator_v6 import TargetEstimator

events = []
est = TargetEstimator(audit=lambda **kw: events.append(kw))
est.reset(1)
for (t, x, y, z, yaw) in [(0.00, 3.769, -2.353, 0.386, -1.23),
                          (0.61, 3.601, -2.431, 0.385, -1.23),
                          (1.22, 3.439, -2.512, 0.398, -1.23)]:
    est.on_pose(t, x, y, z, yaw)

est.measure([298.4, 216.3, 347.3, 255.9], 0.00, decision='a', seq=1)
est.measure([254.0, 235.0, 315.0, 302.0], 0.61, decision='b', seq=2)
print('range at 0.61 =', round(est.range_m, 3), ' cx_eff =', round(est.cx_eff, 1))
for t in (0.61, 0.80, 1.00, 1.22):
    box = est.predict(t)
    print('predict t=%.2f cx=%.0f size=%.0fx%.0f  (gt centre at 1.22 is 216)' % (
        t, (box[0]+box[2])/2, box[2]-box[0], box[3]-box[1]))
crop = est.crop_params(1.22)
print('crop side', round(crop['side'],1), 'center', [round(v,1) for v in crop['center']])