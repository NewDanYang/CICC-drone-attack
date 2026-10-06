#!/usr/bin/env bash
# Capture real /rflysim/sensor2 frames across a full official trial so ArUco
# settings can be replayed against actual competition imagery.
#
# Two races bit earlier attempts, both fixed here:
#   1. waiting for the trial lock before the trial had created it -> capture
#      stopped after ~3 s;
#   2. a STALE lock left by a crashed run -> the script thought a trial was
#      already in progress and never started one.
# So: clear any stale lock, start the trial, wait for the lock to appear, then
# for it to disappear.
set -u
export DISPLAY=:20
export XAUTHORITY=/home/ubuntu/.Xauthority
set +u
source /opt/ros/noetic/setup.bash
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u

LOCK=/tmp/tcei_formal_trial.lock

# --- clean slate -----------------------------------------------------------
if [ -d "$LOCK" ]; then
  PID=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    echo "ABORT: a real trial is running (pid $PID)"
    exit 3
  fi
  echo "clearing stale lock (pid '${PID:-none}' not alive)"
  rm -rf "$LOCK"
fi

OUT=/tmp/aruco_frames_$(date +%Y%m%dT%H%M%S)
mkdir -p "$OUT"
echo "capture_dir=$OUT"

setsid nohup python3 /tmp/aruco_capture.py "$OUT" /rflysim/sensor2/img_rgb frame 1.0 \
  > "$OUT/capture.out" 2>&1 < /dev/null &
CAP_PID=$!
sleep 3

cd /home/ubuntu/tcei_baseline_tools
rm -f /tmp/trial_aruco_capture.log
setsid nohup bash ./run_formal_trial.sh red > /tmp/trial_aruco_capture.log 2>&1 < /dev/null &

# Phase 1: wait for the lock to appear (up to 60 s).
appeared=0
for i in $(seq 1 60); do
  if [ -d "$LOCK" ]; then echo "trial lock appeared at ${i}s"; appeared=1; break; fi
  sleep 1
done
if [ "$appeared" != 1 ]; then
  echo "WARN: trial lock never appeared; trial log follows"
  tail -5 /tmp/trial_aruco_capture.log
fi

# Phase 2: wait for it to disappear (trial over).
for i in $(seq 1 400); do
  [ -d "$LOCK" ] || { echo "trial lock released at ${i}s"; break; }
  sleep 2
done

sleep 2
kill -INT "$CAP_PID" 2>/dev/null
sleep 2
kill -KILL "$CAP_PID" 2>/dev/null

echo "saved=$(ls "$OUT"/*.png 2>/dev/null | wc -l) frames in $OUT"
echo "trial_result:"
grep -E "total_time|mission_success|failure_stage" "$OUT"/../trial_aruco_capture.log 2>/dev/null | tail -3
echo "$OUT" > /tmp/last_aruco_capture_dir
