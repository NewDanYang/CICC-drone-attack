#!/usr/bin/env bash
set -euo pipefail

# Observe an untouched, disarmed simulator scene for the same time span as a
# formal mission plus the delayed actor-settle observation.
tools="${TCEI_HIT_V2_TOOLS:-/home/ubuntu/tcei_hit_balloon_v2_tools}"
trial_lock=/tmp/tcei_formal_trial.lock
control_dir="${1:?usage: run_idle_scene_control.sh OUTPUT_DIR}"
test ! -e "$trial_lock"
mkdir "$trial_lock"
printf '%s\n' "$$" > "$trial_lock/pid"
release_lock() {
    if [[ -f "$trial_lock/pid" && "$(cat "$trial_lock/pid")" == "$$" ]]; then
        rm -f "$trial_lock/pid"
        rmdir "$trial_lock" 2>/dev/null || true
    fi
}
trap release_lock EXIT
set +u
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
timeout 5 rostopic echo -n 1 /mavros/state | grep -q 'armed: False'
mkdir -p "$control_dir"
date -u +'%FT%TZ' > "$control_dir/start_utc.txt"
python3 "$tools/scene_snapshot.py" before "$control_dir"
sleep 120
timeout 5 rostopic echo -n 1 /mavros/state | grep -q 'armed: False'
python3 "$tools/scene_snapshot.py" after "$control_dir"
sleep 145
timeout 5 rostopic echo -n 1 /mavros/state | grep -q 'armed: False'
python3 "$tools/scene_snapshot.py" settled "$control_dir"
date -u +'%FT%TZ' > "$control_dir/end_utc.txt"
