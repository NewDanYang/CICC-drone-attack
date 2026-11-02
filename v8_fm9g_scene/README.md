# v8 — FM9G4B-V perception for all non-balloon targets

Branch `research/fm9g-v8-scene-perception`, based on `research/fm9g-v6-servo-closed-loop@9e8e8ba`.
Status: **code complete and tested offline here; nothing deployed, nothing flown.** No FM9G
inference has run on this code yet (this workspace has no GPU or model weights). Every
claim about FM9G accuracy below is a hypothesis that `tools/offline_eval.py` must confirm on
real frames before any flight.

## 1. Why 6.3 failed (diagnosis from code + report numbers)

| Evidence (6.3 REPORT) | Mechanism |
|---|---|
| Debug image: box over the brick obstacle, score 0.62 | `frame_locator.py` reuses the balloon presence sweep: ask "is there a square frame?" on masked crops and treat the flip point as the box edge. That suits a small solid blob. A large hollow frame next to brick blocks has no clean flip point, and the brick blocks also answer "yes". |
| 19 rejections, x ≈ 1.81–1.85 m, y −1.47…−0.26 m | TargetLocator gets depth only from box size (1.3 m·320/px). The true frame at x=3.25 from observe_pos is ~132 px wide; x≈1.83 needs a ~240 px box (≈1.8× too big); the y swing implies ~220 px centre jumps. `tests/test_geometry.py::test_report_failure_is_reproduced_by_an_oversized_box` reproduces this exactly. |
| `好的，请描述您的任务需求。` intermittently, reproducible with seed 702 | `mission_once.py` decodes both the prompt-injection reply and the command reply with `sampling=True`. A fixed seed reproduces the failure, so it is a sampling outcome. A 3× retry hides it; greedy decoding removes it. |

Unused resource: the forward **depth camera** `/rflysim/sensor0/Depth_Cloud` shares sensor1's mount
(Config.json). The rules FAQ says depth should come from the depth camera.

## 2. Design

```
BT node Fm9gLocate ──"start <target> <id>"──► /fm9g/scene_request ──► SceneBridge (in mission_once.py, shared model+lock)
        ▲                                                              │ per new image:
        │                                                              │  1 FM9G native <box> (448 px, greedy)
        │                                                              │  2 FM9G yes/no verify on crop, P(是) ≥ 0.7 (contrastive prompt)
        │                                                              │  3 metric position + gates
        │                                                              │     front: depth-cloud ring depth; frame box size must agree with it
        │                                                              │     down : ray ∩ ground plane; metric size must be plausible
        └── N agreeing samples, median ◄── /fm9g/target_world/<target> (PointStamped, world ENU)
            → blackboard → existing GoTo / PlanningControl fly to it
```

| Stage | Official behaviour | v8 (`/fm9g_scene/enabled` = true) | On FM9G timeout |
|---|---|---|---|
| Forward frame | YOLO → TargetLocator (size-depth) | `Fm9gLocate square_frame` → `{frame_center}` | **FAILURE** (no preset may stand in: no-指点飞行 rule) |
| ArUco | GoTo fixed hover_pos, OpenCV decodes | GoTo hover_pos → `Fm9gLocate aruco_marker` (down cam) → GoTo `{aruco_hover}` centred over marker → OpenCV decodes | official hover_pos |
| Reverse frame | reuse `{frame_center}` | GoTo `return_observe_pos` → `Fm9gLocate square_frame` (expected = `{frame_center}`) → `{frame_center_return}` | forward `{frame_center}` (perceived earlier) |
| Landing | GoTo fixed return_pos, Land | GoTo return xy @1.2 m → `Fm9gLocate landing_pad` (down cam) → GoTo `{landing_pos}` → Land | official return_pos |
| Pillars | not recognised | recognised + located + shown while idle (pre-balloon); **not fed to the planner** | — |

No YOLO, HSV, colour threshold or simulator truth is used anywhere in this path. ArUco **decoding**
stays OpenCV, as the task allows. YOLO's `square_frame` class is removed from `detection_params.yaml`
(byte-identical to the 6.3 candidate YAML, MD5 `d0a39530…`).

Files:

| Path | Role |
|---|---|
| `code/fm9g_scene/geometry.py` | camera models, depth projection, ring depth, ground intersection (pure numpy) |
| `code/fm9g_scene/targets.py` | the four classes: prompts, camera, physical size |
| `code/fm9g_scene/model_io.py` | native-box + verify calls; guards the balloon bridge's global `scale_resolution=224` |
| `code/fm9g_scene/pipeline.py` | gates; **shared by flight and offline eval** |
| `code/fm9g_scene/bridge.py` | ROS bridge, audit log, saved inputs, `/fm9g/scene_debug_image` + "FM9G scene perception" window (own thread) |
| `code/fm9g_scene/presence.py` | v7 file, unchanged (MD5 `678ac506…`) |
| `cpp/fm9g_locate.cpp` | BT node; auto-built by the perception glob |
| `patches/patch_bt_ros.py` | templates above; refuses unless bt_ros.cpp MD5 = `f3883b30…` (the server's current file) |
| `patches/patch_mission_once.py` + `entry_main.py.txt` | greedy decoding + bridge entry; AST-checks every other helper; keeps CRCRLF/BOM |
| `tools/capture_scene.py` | records real frames + odom + depth during an ordinary trial |
| `tools/offline_eval.py` | runs the flight pipeline on captures; scores vs YOLO (frame) / OpenCV (marker) offline |
| `tools/command_check.py` | no-flight command generation check over 5 phrasings |
| `tools/deploy.sh`, `tools/rollback.sh` | backup + MD5, patch, build, verify; full undo |

## 3. What is verified here, and what is not

| Verified in this workspace | Result |
|---|---|
| Geometry: projection, ring depth, size↔depth gate, ground intersection with tilt | 13 tests pass |
| Bridge wiring with fake ROS + stubbed model: decoding, stamp/odom matching, all gates, one sample per image, request protocol | 9 tests pass (a real double-count bug was found and fixed here) |
| Clock robustness: camera header stamps in a different clock domain from ROS time (6.3 noted mismatched clocks) still match pose by receive time; samples are stamped in ROS time for Fm9gLocate | tested (bridge + capture tool) |
| Patched `commandToXmlNode` compiled and run; XML parsed; **enabled=false output byte-identical to official** | yes |
| `fm9g_locate.cpp` syntax against the repo's real BehaviorTree.CPP headers (ROS stubbed) | compiles, no warnings |
| mission_once patch on LF and CRCRLF+BOM inputs; only the two sampling flags change in helpers | yes |
| deploy.sh / rollback.sh end-to-end in a fake tree (catkin stubbed); rollback restores all MD5s | yes |
| Offline-eval reference: OpenCV ArUco on the real in-flight screenshot in this repo | marker found, ~200 px |
| Down-camera convention check detects mirror/90°/180° errors; refuses to judge without pose diversity | yes (synthetic) |

**Not verified (needs the server):** FM9G native-box accuracy on these four targets; verify-score
calibration; per-call latency; the downward camera's image orientation (`DOWN_CAM_R` is an
assumption); the real catkin build; whether `return_observe_pos` 4.6;-0.4;1.0 is collision-free;
whether greedy decoding fixes command generation for the official phrasings; any flight.

## 4. Server procedure (each step gates the next; stop and report on failure)

0. Check the server is free (AGENTS.md §9). Do not touch another person's lock.
1. **Capture, no code change.** Start the ROS-python capture, then run one ordinary official trial
   (`run_formal_trial.sh red`):
   `python3 tools/capture_scene.py --out /root/gpufree-data/fm9g_v8/capture_<ts>`
   Repeat for purple/blue if time allows (three captures give more viewpoints).
2. **Offline gate** (conda python, GPU, nothing else using the model):
   `offline_eval.py --capture <dir> --out <new dir> --legacy-sweep --simulate-balloon-processor`
   Pass criteria — all must hold:
   - `square_frame`: on frames where YOLO sees the whole frame, recall ≥ 80 %, **0 mislocalised**
     (accepted with IoU < 0.5), world std ≤ 0.10 m; `legacy_sweep` row is the A/B record.
   - `aruco_marker`: recall vs OpenCV ≥ 80 %, 0 mislocalised; `down_camera_convention` = PASS.
   - `landing_pad`, `pillar`: every green box on `sheet_*.jpg` is on the right object.
   - median latency per target ≤ 1.5 s (else each locate stage costs > 5 s).
   If `square_frame` fails: do not fly. Options are a LoRA on independently labelled frames
   (FAQ-permitted), or a different prompt; decide with the author.
3. **Deploy:** `bash tools/deploy.sh /root/gpufree-data/fm9g_v8/backup_<ts>` → `VERIFIED_DEPLOY`.
   Full environment restart (YAML reload).
4. **Command check:** `command_check.py --mission /home/ubuntu/model/mission_once.py --out …`.
   Require 10/10. Re-run on the official five instruction sets on match day.
5. **Flights:** 3–5 per colour, alternating with baseline (`rosparam set /fm9g_scene/enabled false`,
   no rebuild needed). Per trial record: each stage pass/fail, `FM9G_LOCATE_SUCCESS/FALLBACK/TIMEOUT`
   lines with times, `{frame_center}` vs the offline world median, ArUco decode, landing offset,
   total time, collisions. A FALLBACK counts as "FM9G did not drive this stage".

## 5. Mapping to the acceptance list

| Requirement | How v8 meets it | Open |
|---|---|---|
| 1 FM9G alone classifies + gives a usable box/position | native box + FM9G verify; position from depth camera (front) or ground plane (down) | accuracy unproven until step 2 |
| 2 Results drive the existing chain | blackboard positions consumed by unchanged GoTo / PlanningControl / ArucoDetector / Land | — |
| 3 Forward frame, ArUco, reverse frame, landing | all four templates | reverse observe waypoint needs a sim check |
| 4 Full-sim accuracy, control, window, no regression | window + audit + saved inputs; per-stage fallback = official behaviour; runtime A/B switch | step 5 not run |
| 5 With balloons, cover all official classes | frame, pillar, ArUco marker, landing pad here | **balloons are still YOLO in the stable build; v7 FM9G balloon is 0/11 physical hits** — the 10-point claim needs that solved too |

## 6. Risks and decisions for the author

- **Time cost:** each locate stage waits for `min_samples`=3 FM9G decisions (~1 s each, unmeasured):
  roughly +10–15 s per mission across four stages, plus the landing observe climb.
- **Forward frame now FAILs on timeout** (20 s) instead of hanging forever in TargetLocator.
  Both end the stage, but this surfaces the failure.
- **Pillars** are recognised and located but not given to Ego-Planner (it already avoids them via
  the depth cloud). Feeding FM9G pillar positions to the planner is a separate change.
- **`return_observe_pos`** is a new observation waypoint (like the official `observe_pos`). Set it to
  `""` to skip reverse re-recognition and reuse `{frame_center}` (rule-compliant per 6.0 §1).
- **Combined with the balloon candidate:** `entry_main.py.txt` starts both bridges with
  `FM9G_BALLOON_BRIDGE=1`; the v7 `bt_ros` patch expects a different baseline MD5 and must be
  re-anchored onto this patched file (its one `<TargetTracker object_name=` anchor still exists once).

## 7. Rollback

- Runtime, no rebuild: `rosparam set /fm9g_scene/enabled false` → next mission uses the exact
  official XML (verified byte-identical). The scene bridge still runs but receives no requests.
- Full: `bash tools/rollback.sh <backup_dir>` → restores the three files, removes the node and
  package, rebuilds with `--force-cmake`, checks MD5s. Then restart the environment.
