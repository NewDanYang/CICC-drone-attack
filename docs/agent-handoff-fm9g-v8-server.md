# Agent handoff: validate FM9G v8 (non-balloon targets) on the simulation server

**From:** the agent that wrote v8 (cloud session, no SSH access). **To:** the agent with SSH access.
**Branch:** `research/fm9g-v8-scene-perception` (pushed). **Design + rationale:** `v8_fm9g_scene/README.md` — read §1–§4 first.
**Also read:** `AGENTS.md` §3 (evidence rules), §6 (traps), §9 (shared server).

Your job is to run the work below in order, stop at every gate whose criteria fail, and send
back the evidence listed in §7. **Do not tune or rewrite the v8 algorithm yourself.** If a gate
fails, collect the evidence and stop; the author will change the code. The only exceptions are
environment problems you can fix without touching v8 logic (paths, missing pip packages,
locks); record every such fix.

---

## 0. Access and hard rules

```
ssh -p 30811 root@120.209.70.195      # password: ask the user; never write it into any file or commit
```
Note: older docs say port 30316; this instance (L40) is **30811**. The 6.3 report says this
instance lacks the old balloon multimodal bridge — v8 does not need it.

1. Do not change: VisualServo, safety boundaries, launch speeds/waypoints, Ego-Planner settings,
   anything balloon-related, the prompt file, the FM9G weights.
2. Before any change: record MD5s; after any test session: leave the server either fully on the
   baseline (rollback verified by MD5) or explicitly on v8 with the backup path written in your report.
3. **Full environment restart before every formal trial** (`AGENTS.md` §2.3 — `DISPLAY=:20`,
   `XAUTHORITY=/home/ubuntu/.Xauthority`). Check `/tmp/tcei_formal_trial.lock` and
   `/tmp/tcei_sim_environment.lock` first; only clear a lock whose recorded PID is dead.
4. Classify every failed trial as one of: **v8 perception**, **command generation**,
   **environment** (sim/node died, MAVROS, lock), **control/other**. Never count an environment
   failure against v8, and never count a `FM9G_LOCATE_FALLBACK` stage as an FM9G success.
5. Never report "works/looks fine". Report numbers, sample sizes, and counter-examples.

---

## 1. Phase 0 — preflight (no changes)

```bash
cd /root/gpufree-data && git clone -b research/fm9g-v8-scene-perception \
   https://github.com/NewDanYang/CICC-drone-attack cicc-v8 || (cd cicc-v8 && git pull)
cd cicc-v8 && git log --oneline -3
nvidia-smi
ls -d /tmp/tcei_*.lock 2>/dev/null; pgrep -af "[m]ission_once.py"
md5sum /home/ubuntu/model/mission_once.py \
       /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp \
       /home/ubuntu/catkin_ws/src/object_det/config/detection_params.yaml
ls /home/ubuntu/model/FM9G4B-V | head; ls /home/ubuntu/model/prompts
```

Expected MD5s (from the 6.3 report; the patchers refuse to run if they differ):

| File | Expected |
|---|---|
| mission_once.py | `dcc050dd1daa1792a7312345932d0fcb` |
| bt_ros.cpp | `f3883b30c69f3bdc248d50ac9fc0ad9e` |
| detection_params.yaml | `3590c240ecfbc180f4c98b105c540ae8` |

If any differs: **stop**, report the actual MD5s and `diff` against the repo copies; the author re-anchors.

With the simulator running (start it if needed), record the real topic interfaces — v8 assumes them:
```bash
source /opt/ros/noetic/setup.bash; source /home/ubuntu/catkin_ws/devel/setup.bash
rostopic list | grep -E "rflysim|mavros/local_position" 
rostopic hz -w 5 /rflysim/sensor1/img_rgb /rflysim/sensor2/img_rgb /rflysim/sensor0/Depth_Cloud  # Ctrl-C after ~10 s
rostopic echo -n 1 --noarr /rflysim/sensor0/Depth_Cloud | head -40     # fields, point_step, width/height, frame_id
rostopic echo -n 1 /rflysim/sensor1/img_rgb/header; rostopic echo -n 1 /rflysim/uav1/local/odom/header
rosrun tf tf_echo world base_link 2>/dev/null | head -5 || true
```
Save all of this to `preflight.txt`.

## 2. Phase 1 — no-flight server check (≈20 min, changes nothing)

Stop any running `mission_once.py` (it holds the GPU), then:
```bash
cd /root/gpufree-data/cicc-v8/v8_fm9g_scene && bash tools/server_check.sh
```
If step 4 says no images were found, locate the 6.3 frame-audit images
(`find / -path "*multimodal_frame_v1*/images" -type d 2>/dev/null`, or extract them from
`chain2_evidence.tar.gz`) and re-run with `IMGS=<dir> bash tools/server_check.sh`.

Fix-and-retry is allowed only for environment errors (missing `pytest`, import path, ROS not
sourced). If `offline_eval.py` crashes inside model code (`model.chat`, `get_vllm_embedding`),
**stop** and send the traceback.

**Gate 1 (report all, continue only if a–c hold):**
- a. unit tests: 22 passed
- b. both patch dry-runs print `out md5` / `patched` (no refusal)
- c. `command_greedy.json` passed ≥ 9/10
- d. (informational) `command_original.json` result, for the before/after record
- e. (informational) `eval_images/summary.json` square_frame vs legacy sweep — send it even if bad

## 3. Phase 2 — capture real frames during ordinary baseline flights (no v8 code active)

The baseline must be unmodified (Phase 0 MD5s). Full restart, then in one shell (ROS python):
```bash
source /opt/ros/noetic/setup.bash; source /home/ubuntu/catkin_ws/devel/setup.bash
python3 /root/gpufree-data/cicc-v8/v8_fm9g_scene/tools/capture_scene.py \
   --out /root/gpufree-data/fm9g_v8/capture_$(date +%Y%m%dT%H%M%S)_red
```
and in another: `bash ./run_formal_trial.sh red` (from `/home/ubuntu/tcei_baseline_tools`).
The capture stops itself on `/mission_result`. Check: `wc -l index.jsonl`, counts of `front/`,
`down/`, `cloud/`; there must be front frames **with** `cloud` entries and down frames during the
ArUco hover. Repeat for `blue` (2 captures minimum; purple optional).

Then (GPU free):
```bash
cd /home/ubuntu/model && /opt/conda/envs/demo/bin/python3 \
  /root/gpufree-data/cicc-v8/v8_fm9g_scene/tools/offline_eval.py \
  --capture <capture dir> --out <new dir> --legacy-sweep --simulate-balloon-processor
```
Run once per capture.

**Gate 2 — all must hold to proceed to deployment** (`summary.json` + `sheet_*.jpg`):
- square_frame: recall vs YOLO ≥ 80 % on frames where YOLO sees the whole frame; `mislocalised_iou<0.5` = 0; `world_std_m` ≤ 0.10 in x and y; `world_median` within 0.3 m of (3.25, −0.4) — the launch file's expected_pos — **or** of the YOLO reference's `ref_world`.
- aruco_marker: recall vs OpenCV ≥ 80 %; 0 mislocalised; `down_camera_convention.verdict` = `PASS`. If `INSUFFICIENT pose diversity`, report it (the author decides; do not fake diversity).
- landing_pad and pillar: every green box in the contact sheet is on the correct object (state how many you checked, list any wrong ones by filename).
- median latency per target ≤ 1.5 s.

If Gate 2 fails: **stop, do not deploy.** Send the full eval directories.

## 4. Phase 3 — deploy + command check

```bash
cd /root/gpufree-data/cicc-v8/v8_fm9g_scene
bash tools/deploy.sh /root/gpufree-data/fm9g_v8/backup_$(date +%Y%m%dT%H%M%S)   # must print VERIFIED_DEPLOY
```
Full environment restart (the detector must reload the YAML). Then:
```bash
cd /home/ubuntu/model && /opt/conda/envs/demo/bin/python3 \
  /root/gpufree-data/cicc-v8/v8_fm9g_scene/tools/command_check.py \
  --mission /home/ubuntu/model/mission_once.py --out /root/gpufree-data/fm9g_v8/command_deployed.json
```
**Gate 3:** `VERIFIED_DEPLOY`; 10/10 commands; `rostopic echo -n1 /objects` during a hover shows
**no** `square_frame` objects (YOLO class disabled).

## 5. Phase 4 — flights

### 5.1 Smoke flight (1 × red)
Full restart, `run_formal_trial.sh red`, and while it runs record:
```bash
rostopic echo /fm9g/scene_request > scene_request.txt &
rosbag record -O scene.bag /fm9g/target_world/square_frame /fm9g/target_world/aruco_marker \
  /fm9g/target_world/landing_pad /fm9g/scene_debug_image /mavros/local_position/odom &
```
Also take a desktop screenshot while the "FM9G scene perception" window shows a box (rule 4.4(5)
needs the visualization window; `DISPLAY=:20 import -window root shot.png` or equivalent).

Afterwards collect: `grep -h "FM9G_LOCATE\|Fm9gLocate\|ARUCO ID\|Position out of range" `
over the trial's ROS logs, the bridge audit dir (`/home/ubuntu/tcei_baseline_tools/results/fm9g_scene/<newest>/`),
`mission_once.out`, observer output, and the CSV row.

Check specifically: (a) each of the 4 stages logged `FM9G_LOCATE_SUCCESS` (not FALLBACK/TIMEOUT)
and with what latency; (b) `{frame_center}` vs the offline world median; (c) drone actually
passed through the frame both ways, no collision with frame or pillars; (d) the reverse-pass
observation waypoint `4.6;-0.4;1.0` did not cause a collision (watch the sim view / odom);
(e) ArUco decoded after the `GoTo {aruco_hover}` correction; (f) landing position vs pad centre.

**Gate 4:** stages 1–4 succeeded (balloon outcome is out of scope but record it). If the smoke
flight fails for a v8 reason: stop, report, leave v8 deployed **only if** the failure was safe
(otherwise run `tools/rollback.sh <backup>` and verify).

### 5.2 Paired trials (only after Gate 4)
Alternate candidate and baseline, same colour, full restart before every trial:
```
candidate:  rosparam set /fm9g_scene/enabled true    (default)
baseline:   rosparam set /fm9g_scene/enabled false   (exact official behaviour tree; no rebuild)
```
Set the param **after** the environment restart (it resets the parameter server) and before
`run_formal_trial.sh`. Target: red, purple, blue × 3 candidate + 3 baseline = 18 trials.
Stop early and report if candidate has ≥ 2 v8-attributed stage failures.

Record per trial (one CSV row): timestamp, colour, mode, each stage pass/fail, per-stage
`FM9G_LOCATE_*` result + latency, total time, collisions, failure class (§0 rule 4), evidence path.

## 6. Cleanup

At the end, either:
- leave v8 deployed and say so with the backup path, **or**
- `bash tools/rollback.sh <backup>` → must print `ROLLED_BACK`; verify MD5s equal Phase 0; full restart.
Remove only your own temp files. Never touch other people's results.

## 7. What to send back

One archive (`v8_validation_<date>.tar.gz`) containing:
1. `report.md` — gates reached, pass/fail per criterion with numbers, failure classes, every environment fix you made, final server state (baseline or v8 + backup path).
2. `preflight.txt`
3. Phase 1: the `server_check_*.tar.gz`
4. Phase 2: each capture's `index.jsonl` (+ 20 sample front and 20 down frames), each eval dir (`summary.json`, `results.jsonl`, `sheet_*.jpg`, `calls.jsonl`)
5. Phase 3: deploy backup `*.md5`, `build.log`, `command_deployed.json`
6. Phase 4: per trial: ROS log excerpts (`FM9G_LOCATE`, `ArucoDetector`, `TargetLocator`, safety recovery), bridge `audit.jsonl` + 10 sample images, `mission_once.out`, observer output, screenshot of the perception window; plus the trial CSV.

Do not include the password or any credential in the archive.
