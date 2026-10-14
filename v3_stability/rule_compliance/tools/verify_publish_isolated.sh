#!/usr/bin/env bash
# Exercise the staged rule-compliance entrypoint with real model and ROS publish,
# but on a separate ROS master so no flight controller can receive the command.
set -euo pipefail
out="${1:?usage: verify_publish_isolated.sh output_directory}"
mkdir -p "$out"
set +u
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
export ROS_MASTER_URI=http://127.0.0.1:11312
export PYTHONIOENCODING=utf-8
ln -sfn /home/ubuntu/model/prompts /tmp/rule_compliance/prompts
ln -sfn /home/ubuntu/model/FM9G4B-V /tmp/rule_compliance/FM9G4B-V
setsid roscore -p 11312 > "$out/roscore.out" 2>&1 < /dev/null &
core_pid=$!
cleanup() { kill -TERM -- "-$core_pid" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 1 20); do
  if rostopic list >/dev/null 2>&1; then break; fi
  sleep 1
done
rostopic list > "$out/initial_topics.txt"
timeout 150 rostopic echo -n 1 /mission_command > "$out/mission_command_echo.txt" 2>&1 &
echo_pid=$!
sleep 2
set +e
timeout 150 /opt/conda/envs/demo/bin/python3 /tmp/rule_compliance/mission_once.py \
  '飞机起飞，然后穿过框，再去识别二维码，然后再穿回框，接着去打击蓝色气球，完成后就回到起点并降落；' \
  < /dev/null > "$out/mission_once.out" 2>&1
mission_rc=$?
wait "$echo_pid"
echo_rc=$?
set -e
printf 'mission_rc=%s\necho_rc=%s\n' "$mission_rc" "$echo_rc" > "$out/result.txt"
cat "$out/result.txt"
cat "$out/mission_command_echo.txt"
test "$mission_rc" -eq 0
test "$echo_rc" -eq 0
