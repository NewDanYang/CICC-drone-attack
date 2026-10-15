#!/usr/bin/env bash
# Run three-color formal trials with a verified three-balloon opening scene.
# Start this script detached; reset_scene_checked.sh kills simulator process groups.
set -Eeuo pipefail
tools="${TCEI_HIT_V2_TOOLS:-/home/ubuntu/tcei_hit_balloon_v2_tools}"
runs="${TCEI_RUNS_PER_COLOR:-3}"
max_attempts="${TCEI_MAX_ATTEMPTS_PER_COLOR:-3}"
read -r -a colors <<< "${TCEI_FRESH_COLORS:-red purple blue}"
test "${#colors[@]}" -gt 0
for color in "${colors[@]}"; do
  case "$color" in red|purple|blue) ;; *) echo "invalid color: $color" >&2; exit 2 ;; esac
done
output="${TCEI_FRESH_LOOP_OUTPUT:-/home/ubuntu/tcei_baseline_tools/results/hit_balloon_fresh_$(date +%Y%m%dT%H%M%S)}"
mkdir -p "$output"
printf 'round,color,attempt,trial_dir,runner_rc,pre_count,before_count,settled_count,frame_count,sim_pid,valid\n' > "$output/trials.csv"
echo "$output" > "$output/output_path.txt"
trap 'printf "%s\n" "$?" > "$output/exit_code"' EXIT

set +u
source /opt/ros/noetic/setup.bash
set -u

check_idle() {
  local state
  test ! -e /tmp/tcei_formal_trial.lock
  state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
  grep -q 'armed: False' <<< "$state"
}

recover_after_own_trial() {
  # Some failed formal runs leave PX4 armed in OFFBOARD after the runner and
  # scene-observation wrapper have released their locks. Ask PX4 to land and
  # wait for its own disarm before any simulator reset; never kill an armed sim.
  test ! -e /tmp/tcei_formal_trial.lock
  local state response
  state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
  if grep -q 'armed: False' <<< "$state"; then return; fi
  echo 'own trial left PX4 armed; requesting AUTO.LAND before next reset' | tee -a "$output/progress.log"
  response="$(timeout 8 rosservice call /mavros/cmd/land 'min_pitch: 0.0
yaw: 0.0
latitude: 0.0
longitude: 0.0
altitude: 0.0')"
  grep -q 'success: True' <<< "$response"
  for ((i=0; i<30; i++)); do
    sleep 1
    state="$(timeout 8 rostopic echo -n 1 /mavros/state)"
    if grep -q 'armed: False' <<< "$state"; then
      echo "AUTO.LAND disarmed after ${i}s" | tee -a "$output/progress.log"
      return
    fi
  done
  echo 'PX4 remained armed after AUTO.LAND; stopping before reset' >&2
  exit 8
}

restart_scene() {
  local label="$1" log="$output/reset_${label}.log" pid
  check_idle
  setsid nohup bash "$tools/reset_scene_checked.sh" > "$log" 2>&1 < /dev/null &
  pid=$!
  wait "$pid"
  grep -q 'environment_started=1' "$log"
  check_idle
}

snapshot_count() {
  python3 -c 'import json,sys; rows=[json.loads(x) for x in open(sys.argv[1],encoding="utf-8") if x.strip()]; print(rows[-1]["reported_count"])' "$1"
}

for ((round=1; round<=runs; round++)); do
  for color in "${colors[@]}"; do
    valid=0
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
      label="${round}_${color}_${attempt}"
      check_idle
      pre_dir="$output/pre_${label}"
      mkdir -p "$pre_dir"
      python3 "$tools/scene_snapshot.py" before "$pre_dir" > "$pre_dir/snapshot.out"
      pre_count="$(snapshot_count "$pre_dir/scene_snapshots.jsonl")"
      if [[ "$pre_count" != 3 ]]; then
        echo "$label: found $pre_count actors; resetting scene" | tee -a "$output/progress.log"
        restart_scene "$label"
        python3 "$tools/scene_snapshot.py" after "$pre_dir" > "$pre_dir/post_reset.out"
        pre_count="$(snapshot_count "$pre_dir/scene_snapshots.jsonl")"
        if [[ "$pre_count" != 3 ]]; then
          echo "$label: reset still has $pre_count actors" >&2
          exit 5
        fi
      fi
      sim_pid="$(cat /tmp/tcei_sim_environment.lock/rfly3d_pid)"
      echo "$label: trial starting; actors=$pre_count sim_pid=$sim_pid" | tee -a "$output/progress.log"
      set +e
      TCEI_CAPTURE_REAL_FRAMES=1 TCEI_REQUIRE_FRESH_SCENE=1 \
        bash "$tools/run_with_scene_snapshots.sh" "$color" > "$output/trial_${label}.log" 2>&1
      runner_rc=$?
      set -e
      trial_dir="$(sed -n 's/^experiment_dir=//p' "$output/trial_${label}.log" | tail -1)"
      before_count="" settled_count="" frame_count=0 valid=0
      if [[ -n "$trial_dir" && -f "$trial_dir/scene_snapshots.jsonl" ]]; then
        before_count="$(python3 -c 'import json,sys; rows=[json.loads(x) for x in open(sys.argv[1],encoding="utf-8") if x.strip()]; print(next((r["reported_count"] for r in rows if r["phase"]=="before"),""))' "$trial_dir/scene_snapshots.jsonl")"
        settled_count="$(python3 -c 'import json,sys; rows=[json.loads(x) for x in open(sys.argv[1],encoding="utf-8") if x.strip()]; print(next((r["reported_count"] for r in rows if r["phase"]=="settled"),""))' "$trial_dir/scene_snapshots.jsonl")"
        if [[ -f "$trial_dir/real_frames/frames.jsonl" ]]; then
          frame_count="$(wc -l < "$trial_dir/real_frames/frames.jsonl")"
        fi
        if [[ "$before_count" == 3 && -n "$settled_count" && "$frame_count" -gt 0 ]]; then
          valid=1
        fi
      fi
      printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$round" "$color" "$attempt" "$trial_dir" "$runner_rc" "$pre_count" \
        "$before_count" "$settled_count" "$frame_count" "$sim_pid" "$valid" >> "$output/trials.csv"
      echo "$label: trial_dir=$trial_dir runner_rc=$runner_rc before=$before_count settled=$settled_count frames=$frame_count valid=$valid" | tee -a "$output/progress.log"
      recover_after_own_trial
      if [[ "$valid" == 1 ]]; then break; fi
    done
    if [[ "$valid" != 1 ]]; then
      echo "no valid $color run for round $round after $max_attempts attempts" >&2
      exit 6
    fi
  done
done
echo "complete: $runs valid three-actor trials per requested color" | tee -a "$output/progress.log"
