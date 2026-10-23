#!/usr/bin/env bash
set -uo pipefail

# Wrapper around the unchanged official formal runner. The UE actor snapshots
# bracket one trial; the official runner still owns the shared trial lock/CSV.
color="${1:?usage: run_with_scene_snapshots.sh red|purple|blue}"
case "$color" in red|purple|blue) ;; *) echo "invalid color: $color" >&2; exit 2 ;; esac
tools="${TCEI_HIT_V2_TOOLS:-/home/ubuntu/tcei_hit_balloon_v2_tools}"
runner=/home/ubuntu/tcei_baseline_tools/run_formal_trial.sh
trial_lock=/tmp/tcei_formal_trial.lock
if [[ -d "$trial_lock" ]]; then
  echo "formal trial lock is occupied: $trial_lock" >&2
  exit 3
fi
session="$(mktemp -d "/tmp/hit_scene_${color}_XXXXXXXX")"
echo "scene_session=$session"
python3 "$tools/scene_snapshot.py" before "$session" || exit 4
actor_count="$(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).readline())["reported_count"])' "$session/scene_snapshots.jsonl")"
if [[ "${TCEI_REQUIRE_FRESH_SCENE:-1}" == 1 && "$actor_count" != 3 ]]; then
  echo "fresh scene required: expected 3 balloon actors, found $actor_count; snapshot retained at $session" >&2
  exit 5
fi
if [[ "$actor_count" -lt 1 || "$actor_count" -gt 3 ]]; then
  echo "unexpected balloon actor count $actor_count; snapshot retained at $session" >&2
  exit 5
fi

capture_pid=""
if [[ "${TCEI_CAPTURE_REAL_FRAMES:-0}" == 1 ]]; then
  mkdir -p "$session/real_frames"
  (
    set +u
    source /home/ubuntu/catkin_ws/devel/setup.bash
    set -u
    exec /usr/bin/python3 "$tools/capture_real_frames.py" "$session/real_frames"
  ) >"$session/frame_capture.out" 2>&1 &
  capture_pid="$!"
  sleep 2
  if ! kill -0 "$capture_pid" 2>/dev/null; then
    echo "camera capture did not start; see $session/frame_capture.out" >&2
    exit 6
  fi
fi

gc_session=""
gc_pid=""
if [[ "${TCEI_GC_CONTINUOUS:-0}" == 1 ]]; then
  gc_session="$session/gc_continuous"
  mkdir -p "$gc_session"
  /usr/bin/python3 "$tools/gc_timing_probe.py" "$gc_session" \
    --mode continuous --interval 1.5 --duration 600 \
    --stop-file "$gc_session/stop" > "$gc_session/monitor.log" 2>&1 &
  gc_pid="$!"
  for ((i=0; i<60; i++)); do
    [[ -e "$gc_session/ready" ]] && break
    kill -0 "$gc_pid" 2>/dev/null || break
    sleep 0.5
  done
  if [[ ! -e "$gc_session/ready" ]]; then
    echo "continuous GC monitor failed; see $gc_session/monitor.log" >&2
    [[ -n "$capture_pid" ]] && kill -TERM "$capture_pid" 2>/dev/null || true
    exit 8
  fi
fi

set +e
bash "$runner" "$color" 2>&1 | tee "$session/formal_runner.out"
trial_rc="${PIPESTATUS[0]}"
set -e
if [[ -n "$gc_pid" ]]; then
  # Allow the last collision to be collected before the ordinary `after`
  # snapshot. Both control and treatment use this identical measurement path.
  sleep 3
  touch "$gc_session/stop"
  wait "$gc_pid" || { echo "continuous GC monitor exited with error" >&2; exit 8; }
  [[ "$(cat "$gc_session/exit_code")" == 0 ]] || exit 8
fi
if [[ -n "$capture_pid" ]]; then
  kill -TERM "$capture_pid" 2>/dev/null || true
  wait "$capture_pid" 2>/dev/null || true
fi

trial_dir="$(sed -n 's/^experiment_dir=//p' "$session/formal_runner.out" | tail -1)"
if [[ -z "$trial_dir" || ! -d "$trial_dir" ]]; then
  echo "formal trial did not produce a directory; before snapshot retained at $session" >&2
  exit "$trial_rc"
fi
settle_lock=0
release_settle_lock() {
  if [[ "$settle_lock" == 1 && -f "$trial_lock/pid" \
        && "$(cat "$trial_lock/pid")" == "$$" ]]; then
    rm -f "$trial_lock/pid"
    rmdir "$trial_lock" 2>/dev/null || true
  fi
}
trap release_settle_lock EXIT
if mkdir "$trial_lock" 2>/dev/null; then
  printf '%s\n' "$$" > "$trial_lock/pid"
  settle_lock=1
else
  echo "another trial acquired shared lock before post-trial observation; evidence incomplete" >&2
  exit 7
fi
python3 "$tools/scene_snapshot.py" after "$session" || {
  echo "post-trial scene snapshot failed; raw session retained at $session" >&2
  exit 5
}
settle_seconds="${TCEI_SCENE_SETTLE_SECONDS:-125}"
elapsed=0
for checkpoint in 15 45 90; do
  if (( checkpoint < settle_seconds )); then
    sleep "$((checkpoint - elapsed))"
    python3 "$tools/scene_snapshot.py" late "$session" || {
      echo "intermediate scene snapshot failed; raw session retained at $session" >&2
      exit 5
    }
    elapsed="$checkpoint"
  fi
done
sleep "$((settle_seconds - elapsed))"
python3 "$tools/scene_snapshot.py" settled "$session" || {
  echo "settled scene snapshot failed; raw session retained at $session" >&2
  exit 5
}
cp "$session/scene_snapshots.jsonl" "$trial_dir/scene_snapshots.jsonl"
cp "$session/formal_runner.out" "$trial_dir/scene_runner.out"
if [[ -d "$session/real_frames" ]]; then
  mv "$session/real_frames" "$trial_dir/real_frames"
  cp "$session/frame_capture.out" "$trial_dir/frame_capture.out"
fi
if [[ -n "$gc_session" ]]; then
  cp -r "$gc_session" "$trial_dir/gc_continuous"
fi
python3 "$tools/judge_hit.py" "$trial_dir" | tee "$session/judgement.json"
cp "$session/judgement.json" "$trial_dir/judgement.json"
echo "scene_evidence=$trial_dir/scene_snapshots.jsonl"
exit "$trial_rc"
