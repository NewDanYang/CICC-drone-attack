#!/usr/bin/env bash
set -o pipefail

ROOT=/home/ubuntu/tcei_baseline_tools
OUT=/tmp/fm9g_closedloop_collect_20261101
mkdir -p "$OUT"
: > "$OUT/manifest.tsv"

cleanup() {
  bash /tmp/cleanup_sim.sh >> "$OUT/cleanup.log" 2>&1 || true
  rm -rf /tmp/tcei_formal_trial.lock /tmp/tcei_sim_environment.lock /tmp/px4_lock-*
}

start_env() {
  local idx="$1"
  export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
  cd "$ROOT"
  setsid nohup bash ./start_sim_environment.sh > "$OUT/sim_${idx}.log" 2>&1 < /dev/null &
  local pid=$!
  echo "sim_pid=$pid" >> "$OUT/sim_${idx}.log"
  for _ in $(seq 1 300); do
    if grep -q 'environment_started=1' "$OUT/sim_${idx}.log"; then
      break
    fi
    sleep 1
  done
  if ! grep -q 'environment_started=1' "$OUT/sim_${idx}.log"; then
    echo 'environment_started=0' >> "$OUT/sim_${idx}.log"
    return 1
  fi
  source /opt/ros/noetic/setup.bash
  timeout 15 rostopic echo -n1 /mavros/state > "$OUT/state_${idx}.txt" 2>&1 || true
  timeout 15 rostopic echo -n1 /mavros/local_position/odom > "$OUT/odom_${idx}.txt" 2>&1 || true
  return 0
}

run_one() {
  local idx="$1" color="$2"
  echo "START\t$idx\t$color\t$(date -Is)" >> "$OUT/manifest.tsv"
  cleanup
  if ! start_env "$idx"; then
    echo "ENV_FAIL\t$idx\t$color\t$(date -Is)" >> "$OUT/manifest.tsv"
    cleanup
    return 0
  fi
  cd "$ROOT"
  bash ./run_formal_trial.sh "$color" > "$OUT/trial_${idx}_${color}.log" 2>&1 || true
  local trial_dir
  trial_dir=$(find "$ROOT/results/formal_trials" -maxdepth 1 -mindepth 1 -type d -name "*_${color}_A0" -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
  local observer="$trial_dir/observer.out"
  local mission="$trial_dir/mission_once.out"
  local audit
  audit=$(sed -n 's/.*evidence=\([^ ]*\).*/\1/p' "$mission" 2>/dev/null | head -1)
  local audit_ok=0 images_ok=0
  test -f "$audit/audit.jsonl" && audit_ok=1
  test -d "$audit/images" && images_ok=1
  printf 'DONE\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$idx" "$color" "$(date -Is)" "$trial_dir" "$audit" "$audit_ok" "$images_ok" "$observer" >> "$OUT/manifest.tsv"
  cleanup
}

run_one 1 red
run_one 2 purple
run_one 3 blue
run_one 4 red
run_one 5 purple
run_one 6 blue
echo "COLLECTION_DONE\t$(date -Is)" >> "$OUT/manifest.tsv"
