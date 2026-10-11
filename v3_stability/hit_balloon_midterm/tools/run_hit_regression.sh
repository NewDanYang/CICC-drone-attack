#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/noetic/setup.bash
source /home/ubuntu/catkin_ws/devel/setup.bash
SESSION=$(cat /home/ubuntu/hit_balloon_resume_current.txt)
COLOR="${1:-red}"
case "$COLOR" in red|purple|blue) ;; *) echo 'Invalid color'; exit 1 ;; esac
RUN="/home/ubuntu/hit_balloon_trials/${COLOR}_regression_$(date +%Y%m%dT%H%M%S)"
mkdir -p "$RUN"
printf '%s\n' "$RUN" > /home/ubuntu/hit_balloon_current_run.txt
# Preserve the settings from the successful exploratory red trial.
rosparam set /balloon_tracking/confidence_threshold 0.5
rosparam set /visual_servo/forward_velocity 0.35
rosparam set /visual_servo/sprint_velocity 0.8
rosparam set /visual_servo/sprint_time 0.4
rosparam set /land/arrival_tolerance 0.10
rosparam set /land/settle_time 1.0
rosparam set /land/settle_speed_threshold 0.15
rosparam dump "$RUN/params.yaml"
sha256sum /home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/goto.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp   /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp   /home/ubuntu/catkin_ws/src/mission_pkg/src/base/target_detector_base.cpp   /home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py   /home/ubuntu/catkin_ws/src/object_det/scripts/det_color.py > "$RUN/version_sha256.txt"
mkdir -p "$RUN/source"
cp /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp "$RUN/source/"
cp /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/goto.cpp "$RUN/source/"
cp /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp "$RUN/source/"
cp /home/ubuntu/catkin_ws/src/mission_pkg/src/base/target_detector_base.cpp "$RUN/source/"
cp /home/ubuntu/catkin_ws/src/object_det/scripts/det_color.py "$RUN/source/"
cp /home/ubuntu/detection_headless.yaml "$RUN/source/"
rosbag record __name:=hit_balloon_recorder -O "$RUN/evidence.bag" \
  /objects /planning/pos_cmd /move_base_simple/goal \
  /rosout /mission_command /mission_result /aruco/detected_id \
  /mavros/state /mavros/extended_state /mavros/local_position/pose \
  /mavros/setpoint_raw/local /rflysim/uav1/local/odom \
  > "$RUN/record.log" 2>&1 &
RECORDER_PID=$!
finish_recording() {
  kill -INT "$RECORDER_PID" 2>/dev/null || true
  wait "$RECORDER_PID" 2>/dev/null || true
}
trap finish_recording EXIT
sleep 3
TRIAL_COLOR="$COLOR" RUN_DIR="$RUN" /usr/bin/python3 -u - <<'PY' | tee "$RUN/observer.txt"
import os, time, json
from pathlib import Path
import rospy
from std_msgs.msg import String, Int32
from sensor_msgs.msg import Image
from mavros_msgs.msg import State
from mavros_msgs.srv import SetMode
from rosnode import kill_nodes

rospy.init_node('hit_regression_observer', anonymous=True)
run = Path(os.environ['RUN_DIR'])
results, ids = [], []
frame_count = [0]
def image_cb(msg):
    frame_count[0] += 1
subs = [
    rospy.Subscriber('/mission_result', String, lambda m: results.append(m.data)),
    rospy.Subscriber('/aruco/detected_id', Int32, lambda m: ids.append(m.data)),
    rospy.Subscriber('/rflysim/sensor2/img_rgb', Image, image_cb, queue_size=1),
]
pub = rospy.Publisher('/mission_command', String, queue_size=1)
abort = rospy.Publisher('/mission_abort', String, queue_size=1)
sent, result, error, final = False, 'NOT_SENT', None, {}
try:
    state = rospy.wait_for_message('/mavros/state', State, timeout=5)
    if not state.connected or state.armed:
        raise RuntimeError('FCU disconnected or armed; no flight command sent')
    deadline = time.monotonic() + 10
    while pub.get_num_connections() == 0:
        if time.monotonic() >= deadline:
            raise RuntimeError('No mission subscriber; no flight command sent')
        time.sleep(0.1)
    time.sleep(1)
    color = os.environ['TRIAL_COLOR']
    command = json.dumps({'commands': ['takeoff', 'detect_aruco', 'hit_balloon:' + color, 'land']})
    (run / 'command.json').write_text(command)
    pub.publish(String(data=command))
    sent = True
    print('Mission sent: takeoff -> detect_aruco -> hit_balloon:' + color + ' -> land', flush=True)
    deadline = time.monotonic() + 240
    while not results and time.monotonic() < deadline:
        time.sleep(0.2)
    result = results[-1] if results else 'OBSERVER_TIMEOUT'
    print('Mission result:', result, 'ArUco IDs:', ids, flush=True)
except Exception as exc:
    error = str(exc)
    print('Observer error:', error, flush=True)
finally:
    if sent:
        try:
            state = rospy.wait_for_message('/mavros/state', State, timeout=5)
            if result != 'SUCCESS' or state.armed:
                abort.publish(String(data='abort'))
                time.sleep(1)
                kill_nodes(['/llm_mission_node'])
                rospy.wait_for_service('/mavros/set_mode', timeout=5)
                land = rospy.ServiceProxy('/mavros/set_mode', SetMode)
                deadline = time.monotonic() + 60
                while state.armed and time.monotonic() < deadline:
                    print('Recovery AUTO.LAND:', land(base_mode=0, custom_mode='AUTO.LAND').mode_sent, flush=True)
                    time.sleep(3)
                    state = rospy.wait_for_message('/mavros/state', State, timeout=5)
            final = {'armed': state.armed, 'mode': state.mode}
        except Exception as exc:
            final = {'recovery_error': str(exc)}
    summary = {'mission_result': result, 'aruco_ids': ids,
               'camera_frames_total_trial': frame_count[0], 'error': error,
               'final_state': final}
    (run / 'observer.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
PY
sleep 3
finish_recording
trap - EXIT
cp "$SESSION/mission.log" "$RUN/mission.log"
cp "$SESSION/aruco.log" "$RUN/aruco.log"
cp "$SESSION/detection.log" "$RUN/detection.log"
/usr/bin/python3 - "$RUN" <<'PY' | tee "$RUN/landing_comparison.txt"
import sys, math
from pathlib import Path
import rosbag
run = Path(sys.argv[1])
rows, events = [], []
with rosbag.Bag(str(run / 'evidence.bag')) as bag:
    for topic, msg, stamp in bag.read_messages(topics=['/rosout','/rflysim/uav1/local/odom']):
        t = stamp.to_sec()
        if topic.endswith('/odom'):
            p = msg.pose.pose.position
            rows.append((t,p.x,p.y,p.z))
        elif any(k in msg.msg for k in ['LandingSettle', 'Requesting mode AUTO.LAND',
                                        'Landed and disarmed', 'ARUCO ID DETECTED',
                                        'Mission Completed', 'SafetyRecovery', 'Visual Servo Started',
                                        'conf_th:', 'SPRINT', 'Sprint completed', 'Target lost']):
            events.append((t,msg.msg))
starts = [t for t,s in events if '[Land]' in s and 'Requesting mode AUTO.LAND' in s]
print('=== Recorded task events ===')
for t,s in events:
    print('%.3f %s' % (t,s))
if starts and rows:
    start = starts[0]
    def near(t):
        return min(rows,key=lambda r:abs(r[0]-t))
    initial = near(start)
    print('=== Position relative to AUTO.LAND request ===')
    for dt in [-1,0,0.5,1,2,3,4,5]:
        r = near(start+dt)
        if abs(r[0]-(start+dt)) > 0.3:
            continue
        print('%+.3fs sim=(%.3f,%.3f,%.3f) drift_from_switch=%.3fm' %
              (r[0]-start,*r[1:],math.hypot(r[1]-initial[1],r[2]-initial[2])))
    landed = [r for r in rows if r[0]>=start and r[3]<=0.03]
    if landed:
        r=landed[0]
        print('First ground sample: offset_from_origin=%.3fm drift_from_switch=%.3fm' %
              (math.hypot(r[1],r[2]),math.hypot(r[1]-initial[1],r[2]-initial[2])))
else:
    print('No complete AUTO.LAND timeline; inspect observer and logs.')
PY
echo '=== Final flight state ==='
timeout 5 rostopic echo -n 1 /mavros/state || true
printf 'Evidence directory: %s\n' "$RUN"

