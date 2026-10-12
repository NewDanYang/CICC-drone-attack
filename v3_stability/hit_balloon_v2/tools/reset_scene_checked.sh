#!/usr/bin/env bash
set -euo pipefail

# Run detached. This deliberately terminates the simulation process groups,
# so the SSH command that launches this script must not share those groups.
trial_lock=/tmp/tcei_formal_trial.lock
sim_lock=/tmp/tcei_sim_environment.lock
test ! -e "$trial_lock"
test -d "$sim_lock"
set +u
source /opt/ros/noetic/setup.bash
set -u
timeout 5 rostopic echo -n 1 /mavros/state | grep -q 'armed: False'
sitl_pid="$(cat "$sim_lock/sitl_pid")"
sim_pid="$(cat "$sim_lock/sim_pid")"
ue_pid="$(cat "$sim_lock/rfly3d_pid")"
test "$(ps -o pgid= -p "$sitl_pid" | tr -d ' ')" = "$sitl_pid"
test "$(ps -o pgid= -p "$sim_pid" | tr -d ' ')" = "$sim_pid"
ps -o cmd= -p "$ue_pid" | grep -q RflySim3D
printf 'old_pids=%s,%s,%s\n' "$sitl_pid" "$sim_pid" "$ue_pid"
kill -TERM -- "-$sim_pid"
kill -TERM -- "-$sitl_pid"
kill -TERM "$ue_pid" || true
sleep 5
for pid in "$sitl_pid" "$sim_pid" "$ue_pid"; do
    if ps -o stat= -p "$pid" 2>/dev/null | grep -qv '^[Z ]*$'; then
        echo "still_alive=$pid" >&2
        exit 7
    fi
done
rm -f "$sim_lock/pid" "$sim_lock/sitl_pid" "$sim_lock/sim_pid" "$sim_lock/rfly3d_pid"
rmdir "$sim_lock"
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
exec bash /home/ubuntu/tcei_baseline_tools/start_sim_environment.sh
