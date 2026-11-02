# Winning plan — what to do now, and through the final (2026-11-02, 20:30 JST)

Written after reading the rules (`打击.pdf`, `规则.txt`), `AGENTS.md`, every stage report, the
`main` branch and today's three server validation rounds. Every number below has its evidence
path. Where something is unknown it says so.

---

## 0. TL;DR

1. **The server used today (port 30811) is running the official demo, not our best build.**
   Its `bt_ros.cpp` (`f3883b30…`) and `visual_servo.cpp` (`a97f5af2…`) are byte-identical to
   `official_baseline/`, and `mission_once.py` (`dcc050dd…`) has no colour guard. Our sealed
   best version (2026-10-19, 8/9 target balloons, 0 wrong balloons) lives in
   `main:v4_innovation_timing/local_audit_rerun_20261027/evidence/frozen_source/`.
   **Tonight's first job is to put the right build on the demo machine and prove it with trials.**
2. **Do not claim the FM9G 10-point bonus tonight.** It requires FM9G to recognise *every*
   class; our non-balloon FM9G localisation failed today (frame 0/104), and mixing with YOLO
   scores nothing. Claiming it and failing code review costs more than it gains.
3. **Only claim innovation points whose document matches the deployed code** — a mismatch is
   −10 per the rules.
4. After tonight, the path to winning the **final** is: one frozen, reproducible build →
   balloon-stage reliability → time → FM9G via LoRA + tracker → sim-to-real for Shenzhen.

---

## 1. Where the points are (100 + bonuses) and where we stand

| Item | Points | Current evidence | Status |
|---|---:|---|---|
| Takeoff | 5 | always passes in recorded trials | ✅ |
| Cross frame | 15 | 9/9 (time-opt report 2026-10-22); today's baseline run passed | ✅ |
| ArUco | 15 | CLAHE node: 21/21 replay frames, 3/3 + 2/2 + 3/3 trials; a historical 20 s callback stall never re-occurred but was never root-caused (`v3_stability/reports/aruco_fix_20261006.md`) | ✅ with residual risk |
| Reverse frame | 15 | 9/9 | ✅ |
| Hit balloon | 25 | sealed version: 8/9 target hit, 0/9 wrong balloon, 1/9 suspected wall contact (`v3_stability/reports/hit_balloon_part1_final/REPORT.md`); official demo baseline earlier: 7/9 with 2/9 double kills (`hit_balloon_part1_1.1`) | ⚠️ biggest base-score risk |
| Return & land | 5 | always passes | ✅ |
| Time ranking | 0–10 | takeoff retry 5→1.5 s + stable-wait candidates kept; 0.40 m/s rolled back (speed compliance) | partial |
| Innovative path planning | 10 | concept used simulator truth → not claimable (`v4_innovation_timing/path_planning_experiment/REPORT.md`, `research_20261030/`) | ❌ |
| Innovation nodes | 1–3 each | 7 candidates drafted; data is "ours before vs after", not "official vs ours" (`v4_innovation_timing/innovation_nodes_draft.md`) | ⚠️ claim only the strongest 1–2 |
| FM9G multimodal recognition | 10 | balloons: best FM9G variant (Stage D) 14/18 clean hits vs YOLO 18/18 (`multimodal_5_13_stage_d_combined`); later v7 variant 0/11 physical; non-balloon zero-shot 0/104 frame, 0/11 marker (today) | ❌ not tonight |
| Penalties | −5 each | collision with an object (−5, two objects = stage 0), no perception window (−5), perception not used for control (−5), doc ≠ code (−10) | must avoid |

Correction to something I said earlier today: "FM9G balloon is 0/11" is true only for the v7
variant. The best FM9G balloon pipeline so far (Stage D, presence sweep + tracking) hit the
target in 14/18 trials. That matters for the FM9G plan in §5.

---

## 2. Tonight — step by step (stop rules included)

First, **confirm what "the deadline tonight" is**: code-package submission, or a live demo?
The steps are the same; the time box changes.

### Step 1 — Identify the build on the machine that will be judged (15 min)
On the demo server, record:
```
md5sum /home/ubuntu/model/mission_once.py \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/visual_servo.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/nodes/action/goto.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/include/nodes/action/goto.h \
  /home/ubuntu/catkin_ws/src/mission_pkg/src/mavros_cnt.cpp \
  /home/ubuntu/catkin_ws/src/mission_pkg/launch/llm_mission.launch \
  /home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py
ls /home/ubuntu/tcei_baseline_tools/results/hit_balloon_final_freeze_20261019/ 2>/dev/null
ls -d /home/ubuntu/cicc_v1_stage_20261005 2>/dev/null
```
Compare with:

| File | Official demo | Sealed best (2026-10-19) |
|---|---|---|
| bt_ros.cpp | `f3883b30…` | `9b1cefe9dfa431418435f7f8f63a60ed` |
| visual_servo.cpp | `a97f5af2…` | `a63b57fa127a23cd8bb8e647f078ff21` |
| goto.cpp / goto.h | official | `f557ace5…` / `ee765e08…` |
| mavros_cnt.cpp | `d73b185a…` | `edcd9397074f44c6028c8dca02902920` (safety-recovery fix) |
| llm_mission.launch | `ef0e8aa0…` | `5550c580a4822e773a331bcef11f0c47` |
| mission_once.py | (no guard) `dcc050dd…` | `fca24bf1142ca8cddfb9e8d39c387a43` (colour guard + fallback, 29 regression tests) |
| aruco_detect_node.py | `e9def27d…` | `0f15e84bdaed68c85d3b6b6ee5e33788` (CLAHE, not in the 7-file freeze) |

### Step 2 — Decide which build to submit (decision, 5 min)
- **If the demo machine already has the sealed MD5s** → keep it, skip to Step 4.
- **If it has the official demo (as 30811 does) and you have ≥ 2 h** → deploy the sealed build
  (Step 3). It is the build with the best balloon evidence and it passed the team's speed
  compliance fingerprints (`main:speed_compliance/approved_fingerprints.json`).
- **If < 2 h** → keep what is there; do not deploy untested.

### Step 3 — Deploy the sealed build with rollback (45–60 min incl. 3 trials)
1. No formal-trial lock, PX4 `armed: False`. Back up every file to be replaced, record MD5s.
2. Source of truth, in order of preference:
   a. the server freeze archive `…/hit_balloon_final_freeze_20261019/final_deployment.tar.gz`
      (`tar -tzf` first; it holds the 7 paths), or
   b. `git show origin/main:v4_innovation_timing/local_audit_rerun_20261027/evidence/frozen_source/<path>`
      and verify each against `manifest.json` (sha256 + bytes). Copy **bytes**, never via a
      Windows shell (`AGENTS.md` §6.1, CRLF).
   c. ArUco CLAHE node: `v3_stability/aruco/aruco_detect_node.py` (`0f15e84b…`).
3. `catkin_make --force-cmake --pkg mission_pkg -j2`, full environment restart, verify MD5s
   and that 3 balloons spawn.
4. **3 trials, one per colour.** Go if ≥ the current machine's record on stages 1–4 and no
   wrong-colour hit; otherwise restore the backups (verify MD5s) and submit the current build.

### Step 4 — Confidence + rule evidence (remaining time)
- More trials if time allows (priority red → blue → purple), full restart each, record stage
  pass/fail, total time, collisions, failure class.
- Screenshots: YOLO detection window + ArUco window visible during frame/QR stages;
  `rostopic echo /mavros/setpoint_raw/local` changing in flight.
- Enter official prompts **one at a time**. A reply without a command block → re-send.

### Step 5 — Submission package 「赛道_队伍名称_单位_联系方式」
- **Source:** exactly the files on the demo machine (copy them off with MD5 list).
- **Technical report:** pipeline (NL → FM9G parsing → BT → control), the stage results table
  above with sample sizes, rule-compliance notes (windows, visual feedback, official
  coordinates per organiser reply in `docs/next-phase-plan-v2.md`).
- **Innovation nodes:** claim at most the two with the strongest evidence *and* deployed code:
  safety-boundary recovery deadlock fix (`mavros_cnt.cpp`) and ArUco CLAHE preprocessing — only
  if those exact files are deployed. Everything else stays out.
- **Do not claim:** FM9G recognition bonus, innovative path planning.
- **PPT:** 6–8 slides — architecture, per-stage reliability numbers, the two innovations, honest
  limitations, what's next.

---

## 3. Major hurdles and how to fix them

### H1 — No single source of truth for "the competition build" (critical, cause of today's confusion)
*Evidence:* two servers (30316 refused connections on 2026-10-30; 30811 used today), two
candidate workspaces (`/home/ubuntu/catkin_ws` vs `/home/ubuntu/cicc_v1_stage_20261005`),
official demo found running where the team assumed its build was; the 2026-10-27 audit notes
the four planner files were restored to official versions in PR #13.
*Fix:* one `release/competition` branch containing exactly the deployed files + a manifest;
one `deploy_release.sh` that installs from it with MD5 checks and rollback; one read-only
`runtime_probe.py` (already in `research_20261030`) run before every trial and before the
demo. No change reaches the server except through this path.

### H2 — Balloon stage (25 pts) is the least reliable base stage
*Evidence:* sealed 8/9; failures come from a moving cart not being found within the 50 s
`Timeout`, wall proximity during approach, and `ForceSuccess` hiding failures
(`hit_balloon_fix_20261012.md`, `hit_balloon_part1_final`).
*Fix (after tonight):* (1) an observer that judges the balloon actually popped (Actor
disappearance) instead of "sprint completed"; (2) approach waypoints tuned per zone with wall
margin (organiser confirmed adjusting demo coordinates is allowed); (3) re-search instead of
`ForceSuccess` when the timeout hits while the target is still visible; (4) 9-trial batches
per change, alternating with the sealed baseline.

### H3 — ArUco callback stall never root-caused
*Fix:* deploy the CLAHE node with its unthrottled `callbacks/s` counter; add a watchdog in
`ArucoDetector` that re-sends the enable command if no callbacks arrive for 2 s.

### H4 — Command generation occasionally returns no command block
*Fix:* the sealed `mission_once.py` already validates colours and has a fallback (29 tests).
If the deployed one lacks it, re-sending the prompt is the operator fallback. Greedy decoding
was tested today and rejected (10/10 but 180 s load, 235 s calls).

### H5 — Time score
*Constraint:* the team's own speed-compliance policy keeps flight speeds at official values.
*Fix:* remove waiting, not speed: takeoff retry 1.5 s and stable-position wait (kept,
validated); shorten observe delays; avoid boundary-recovery loops (each costs ~2 s); a faster
balloon acquisition is the biggest remaining time sink.

### H6 — Penalties
*Fix:* keep perception windows on during demo; avoid wall contact on balloon approach; ensure
every innovation document line matches code; keep the organiser's written answer on preset
coordinates in the package.

### H7 — FM9G 10-point bonus (needs every class)
*Evidence:* zero-shot FM9G cannot localise frame/marker/pad (yes/no scores flat 0.3–0.6);
native `<box>` returns placeholders. Balloons: Stage D 14/18 vs YOLO 18/18.
*Fix (1–2 weeks, after base is frozen):*
1. **LoRA a yes/no "presence" adapter** on crops (officially allowed). Data: today's red capture
   (243 front + 243 down frames with depth and pose) + 2 more captures; labels by people
   (frame/pad/pillars; marker boxes from OpenCV corners). Train on the L40 when no trials run.
2. Plug it into the v8 window search (`research/fm9g-v8-scene-perception`, all integration,
   depth, ground-plane geometry, BT node, tests and gated tooling are done; down-camera
   convention verified on the server).
3. **Balloons:** FM9G initial box → OpenCV CSRT/KCF tracker at camera rate → existing
   VisualServo; FM9G re-verifies the tracked box ~1 Hz and re-detects on loss / jump. Start from
   the Stage D pipeline (14/18), not v7.
4. Same gates as today (offline Gate 2 → deploy → smoke → paired trials). Claim the bonus only
   when all classes pass.

### H8 — Innovative path planning (10)
*Status:* not claimable (simulator truth). *Fix:* only if time remains after H2/H7 — use the
depth cloud for non-target-balloon avoidance cost; must beat official on time or smoothness in
paired trials.

### H9 — Sim-to-real for the Shenzhen final (December)
The final is on real drones with our own laptops. Risks: FM9G needs 8–12 GB VRAM (laptop GPU
may not fit → plan the compute), real camera intrinsics/extrinsics, lighting, real collisions.
*Fix:* get the official hardware/demo docs for the final now; calibrate cameras on day one of
on-site training; keep every perception parameter in config, not code; rehearse the exact
operator procedure (start, prompts one at a time, emergency stop).

### H10 — Process
Single shared server, several agents. Keep: lock checks, MD5 before/after, evidence folders,
"stop at gate" handoffs (worked well today), one owner per directory (`AGENTS.md` §9).

---

## 4. Roadmap after tonight

| When | Goal | Exit criterion |
|---|---|---|
| Day 1–2 | H1: `release/competition` branch + deploy script + runtime probe | Demo machine MD5s == manifest; rollback tested |
| Day 2–5 | H2/H3: balloon observer + approach tuning; ArUco watchdog | 9/9 target hits, 0 wrong, 0 wall frames over 9 trials; ArUco 9/9 |
| Day 3–10 | H7 data + LoRA (parallel, GPU off-hours) | Offline Gate 2 passes on 2 captures |
| Day 8–14 | H7 integration: non-balloon FM9G + balloon tracker | Paired trials ≥ baseline success, all classes by FM9G |
| Day 10–16 | H5 time; innovation docs with official-vs-ours data | Documented time gain over official demo |
| Before final | H9 sim-to-real prep, rehearsal, packaging | Checklist rehearsed twice |

---

## 5. Decisions the team must make

1. What exactly is due tonight (package or demo) and at what time?
2. Deploy the sealed build on the demo machine tonight (Step 2/3) — yes/no?
3. Which 1–2 innovation nodes to claim (only those whose code is deployed)?
4. After tonight: commit 1–2 weeks to the FM9G LoRA + tracker route for the final?
5. Who labels training data (FAQ allows independent annotators; YOLO pre-labels + human check,
   or fully manual)?

---

## 6. Evidence index

| Topic | Path |
|---|---|
| Rules | `打击.pdf`, `规则.txt` |
| Sealed balloon build | `v3_stability/reports/hit_balloon_part1_final/REPORT.md`; source on `main` under `v4_innovation_timing/local_audit_rerun_20261027/evidence/frozen_source/` |
| ArUco | `v3_stability/reports/aruco_fix_20261006.md`, `v3_stability/aruco/` |
| Time optimisation | `v4_innovation_timing/time_optimization/REPORT.md` |
| Speed compliance | `main:speed_compliance/` |
| Path planning | `v4_innovation_timing/path_planning_experiment/REPORT.md`, `main:research_20261030/` |
| FM9G balloons | `v4_innovation_timing/multimodal_5_13_stage_d_combined/REPORT.md`, `v7_servo_closed_loop/REPORT.md` |
| FM9G non-balloon (today) | `v8_fm9g_scene/README.md`, `docs/agent-handoff-fm9g-v8-server.md`, `docs/status-fm9g-nonballoon-20261102.md` |
| Innovation draft | `v4_innovation_timing/innovation_nodes_draft.md` |
