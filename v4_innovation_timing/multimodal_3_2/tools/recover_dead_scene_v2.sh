#!/usr/bin/env bash
# Recover only our recorded simulator groups after the UE process has exited.
set -euo pipefail
test ! -e /tmp/tcei_formal_trial.lock
set +u
source /home/ubuntu/catkin_ws/devel/setup.bash
set -u
timeout 8 rostopic echo -n 1 /mavros/state | grep -q 'armed: False'
/usr/bin/python3 - <<'PY'
import os,signal,subprocess,time
from pathlib import Path
lock=Path('/tmp/tcei_sim_environment.lock')
ue=int((lock/'rfly3d_pid').read_text())
assert not Path('/proc',str(ue)).exists(),'Recorded UE still alive'
assert subprocess.run(['pgrep','-f',r'[.]\/RflySim3D$'],capture_output=True).returncode==1,'Other UE exists'
pids=[]
for name,expected in [('sim_pid',b'/home/ubuntu/catkin_ws/sim_env_start.sh'),
                      ('sitl_pid',b'/home/ubuntu/PX4PSP/SITLRun.sh')]:
    pid=int((lock/name).read_text())
    argv=Path('/proc',str(pid),'cmdline').read_bytes().split(b'\0')
    assert expected in argv,(pid,argv)
    assert os.getpgid(pid)==pid
    pids.append(pid)
print('STOP_OWN_DEAD_SCENE_GROUPS',pids,flush=True)
for pid in pids:os.killpg(pid,signal.SIGTERM)
time.sleep(5)
for pid in pids:
    status=Path('/proc',str(pid),'stat')
    assert not status.exists() or status.read_text().split()[2]=='Z',pid
for name in ('pid','sitl_pid','sim_pid','rfly3d_pid'):(lock/name).unlink(missing_ok=True)
lock.rmdir()
PY
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
exec bash /home/ubuntu/tcei_baseline_tools/start_sim_environment.sh
