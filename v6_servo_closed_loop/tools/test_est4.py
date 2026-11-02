import sys, math
sys.path.insert(0, '.scratch/v6')
from estimator_v6 import TargetEstimator

events = []
est = TargetEstimator(audit=lambda **kw: events.append(kw))
est.reset(1)

# poses copied from the v6.3 purple trial (rfly odom, wall clock offset 45.55 -> t0)
poses = [(0.00, 3.769, -2.353, 0.386, -1.23),
         (0.61, 3.601, -2.431, 0.385, -1.23),
         (1.22, 3.439, -2.512, 0.398, -1.23)]
for (t, x, y, z, yaw) in poses:
    est.on_pose(t, x, y, z, yaw)

# the model boxes the trial actually produced
meas = [(0.00, [298.4, 216.3, 347.3, 255.9]),
        (0.61, [254.0, 235.0, 315.0, 302.0]),
        (1.22, [238.0, 175.0, 276.8, 315.0])]
for (t, box) in meas:
    est.measure(box, t, decision='d', seq=int(t * 10))
    print('after measure t=%.2f  cx_eff=%.1f range=%s' % (t, est.cx_eff, est.range_m))

for t in (0.61, 1.22, 1.40):
    box = est.predict(t)
    print('predict t=%.2f -> %s  size %.0fx%.0f  cx %.0f' % (
        t, [round(v, 1) for v in box], box[2] - box[0], box[3] - box[1],
        (box[0] + box[2]) / 2))

pub = est.publish(1.30)
print('publish@1.30 score', pub['score'], pub['mode'], 'age', round(pub['age_s'], 3),
      'bbox', [round(v, 1) for v in pub['bbox']])
crop = est.crop_params(1.30)
print('crop  side', round(crop['side'], 1), 'center', [round(v, 1) for v in crop['center']])
print('events', [e['kind'] for e in events])