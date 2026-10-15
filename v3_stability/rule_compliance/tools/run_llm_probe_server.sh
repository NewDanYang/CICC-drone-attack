#!/usr/bin/env bash
# Run one deployed-model probe on the simulation server; does not publish commands.
set -euo pipefail
mode="${1:?usage: run_llm_probe_server.sh targeted|full}"
root=/tmp/rule_compliance
output="$root/$mode"
mkdir -p "$output"
trap 'printf "%s\n" "$?" > "$output/exit_code"' EXIT
set +u
source /opt/ros/noetic/setup.bash
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
export PYTHONUNBUFFERED=1
cd /home/ubuntu/model
if [ "$mode" = targeted ]; then
  exec_args=(--samples 5 --case-ids blue_ball,red_yanse,distractor_color,step_land)
elif [ "$mode" = full ]; then
  exec_args=(--samples 3)
else
  echo "unknown probe mode: $mode" >&2
  exit 2
fi
/opt/conda/envs/demo/bin/python3 "$root/llm_paraphrase_probe.py" \
  --module /home/ubuntu/model/mission_once.py --output "$output" "${exec_args[@]}"
