#!/usr/bin/env bash
set -o pipefail

ROOT=/home/ubuntu/tcei_baseline_tools
TOOLS=/home/ubuntu/tcei_hit_balloon_v2_tools
SWITCH=/home/ubuntu/multimodal_v2/tools/switch_condition_v2.sh
RESET=/home/ubuntu/tcei_hit_balloon_v2_tools/reset_scene_checked.sh
BACKUP=/home/ubuntu/multimodal_v2_backup_20261026T0009
OUT=/home/ubuntu/tcei_baseline_tools/results/stage_d_20261101_retry
mkdir -p "$OUT"
printf 'pair\tcolor\tcondition\ttrial_rc\ttrial_dir\tstatus\tmd5_file\n' > "$OUT/manifest.tsv"

cleanup() {
  bash /tmp/cleanup_sim.sh >> "$OUT/cleanup.log" 2>&1 || true
  rm -rf /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock /tmp/px4_lock-*
}

start_env() {
  local label="$1"
  export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
  cd "$ROOT"
  setsid nohup bash ./start_sim_environment.sh > "$OUT/start_${label}.log" 2>&1 < /dev/null &
  local pid=$!
  echo "start_wrapper_pid=$pid" >> "$OUT/start_${label}.log"
  for _ in $(seq 1 300); do
    grep -q 'environment_started=1' "$OUT/start_${label}.log" && return 0
    sleep 1
  done
  return 1
}

switch_condition() {
  local condition="$1" label="$2"
  bash "$SWITCH" "$condition" "$BACKUP" no-reset > "$OUT/switch_${label}.log" 2>&1 || return 1
  # A switch with no-reset only changes the deployed package. Restart UE and
  # all ROS nodes before the flight, so each row has a fresh environment.
  setsid nohup bash "$RESET" > "$OUT/reset_${label}.log" 2>&1 < /dev/null &
  local pid=$!
  wait "$pid" || return 1
  grep -q 'environment_started=1' "$OUT/reset_${label}.log"
}

run_row() {
  local pair="$1" color="$2" condition="$3"
  local label="p${pair}_${condition}_${color}"
  cleanup
  if ! start_env "$label"; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pair" "$color" "$condition" 99 '' env_start_failed '' >> "$OUT/manifest.tsv"
    cleanup
    return 0
  fi
  if ! switch_condition "$condition" "$label"; then
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pair" "$color" "$condition" 98 '' switch_failed '' >> "$OUT/manifest.tsv"
    cleanup
    return 0
  fi
  python3 /home/ubuntu/multimodal_v2/p12e_stage_b/patches/deploy_v2.py status "$BACKUP" > "$OUT/status_${label}.json" 2>&1 || true
  md5sum /home/ubuntu/multimodal_v2/p12e_stage_b/v2/runtime.py \
    /home/ubuntu/model/fm9g_perception/runtime.py \
    /home/ubuntu/model/mission_once.py \
    /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp \
    /home/ubuntu/catkin_ws/devel/lib/mission_pkg/bt_ros \
    /home/ubuntu/catkin_ws/devel/lib/multimodal_target_tracker.so \
    > "$OUT/md5_${label}.txt" 2>&1 || true
  set +e
  bash /tmp/stage_d_trial.sh "$color" "$label" "$OUT" > "$OUT/orchestration_${label}.log" 2>&1
  local rc=$?
  set -e
  local trial_dir=''
  [[ -f "$OUT/session_${label}/trial_dir.txt" ]] && trial_dir=$(cat "$OUT/session_${label}/trial_dir.txt")
  local status='completed'
  [[ -f "$OUT/session_${label}/status.txt" ]] || status='missing_status'
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pair" "$color" "$condition" "$rc" "$trial_dir" "$status" "$OUT/md5_${label}.txt" >> "$OUT/manifest.tsv"
  cleanup
}

# Nine fixed color pairs. Candidate is always first; baseline is second;
# colors alternate within each round.
for pair in 1 2 3; do
  for color in red purple blue; do
    run_row "$pair" "$color" candidate
    run_row "$pair" "$color" baseline
  done
done
printf 'COLLECTION_DONE\t%s\n' "$(date -Is)" >> "$OUT/manifest.tsv"
cleanup
