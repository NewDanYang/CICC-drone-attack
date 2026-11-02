#!/usr/bin/env bash
set -euo pipefail
sim_lock=/tmp/tcei_sim_environment.lock
trial_lock=/tmp/tcei_formal_trial.lock
if [ -e "$trial_lock" ]; then echo "TRIAL_LOCK_PRESENT"; ls -la "$trial_lock"; fi
if [ ! -d "$sim_lock" ]; then echo "NO_SIM_LOCK"; exit 0; fi
sitl_pid="$(cat "$sim_lock/sitl_pid" 2>/dev/null || echo)"
sim_pid="$(cat "$sim_lock/sim_pid" 2>/dev/null || echo)"
ue_pid="$(cat "$sim_lock/rfly3d_pid" 2>/dev/null || echo)"
echo "pids=$sitl_pid,$sim_pid,$ue_pid"
for p in "$sim_pid" "$sitl_pid"; do
  [ -n "$p" ] && kill -TERM -- "-$p" 2>/dev/null || true
done
[ -n "$ue_pid" ] && kill -TERM "$ue_pid" 2>/dev/null || true
sleep 6
for p in "$sitl_pid" "$sim_pid" "$ue_pid"; do
  if [ -n "$p" ] && ps -o stat= -p "$p" 2>/dev/null | grep -qv '^[Z ]*$'; then echo "still_alive=$p"; kill -KILL -- "-$p" 2>/dev/null || true; kill -KILL "$p" 2>/dev/null || true; fi
done
sleep 2
pkill -f "[r]flysim" 2>/dev/null || true
pkill -f "[C]opterSim" 2>/dev/null || true
pkill -f "[R]flySim3D" 2>/dev/null || true
pkill -f "[r]oslaunch" 2>/dev/null || true
sleep 3
rm -f "$sim_lock/pid" "$sim_lock/sitl_pid" "$sim_lock/sim_pid" "$sim_lock/rfly3d_pid"
rmdir "$sim_lock" 2>/dev/null || true
echo "TORN_DOWN"
ps -eo comm | sort | uniq -c | sort -rn | head -5
