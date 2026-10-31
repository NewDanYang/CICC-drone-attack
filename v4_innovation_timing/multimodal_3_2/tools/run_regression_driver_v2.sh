#!/usr/bin/env bash
set -euo pipefail
set +u
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
exec /usr/bin/python3 -u /home/ubuntu/multimodal_v2/tools/run_regression_v2.py \
  --demos /home/ubuntu/multimodal_v2/demo_review.json \
  --backup /home/ubuntu/multimodal_v2_backup_20261026T0009 \
  --output /home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_20261026 \
  --hours 4 \
  --initial-ready-log /home/ubuntu/tcei_baseline_tools/results/multimodal_v2_regression_startup_aborted_20261026/01_switch.log
