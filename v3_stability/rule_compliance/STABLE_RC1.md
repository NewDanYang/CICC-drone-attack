# Stable RC1 integration status

Updated through diagnostic 06 on 2026-11-02. Candidate remains unqualified; formal acceptance is 0/9.

Base main: `99096001661c8bcb45890792fe0126c044a8f91d`.
Selected PR #24: `29eec32c9262b13713114fc8e6162d75cd0793b1`.
Branch: `release/stable-rc1`; this snapshot is being published at the user's request. It is not an accepted release.
Original `/home/ubuntu/catkin_ws` is preserved. Research PRs #21/#22/#23 remain excluded.

## Reproducible integration

`materialize_stable_rc1_workspace.py` starts from repository main's mission_pkg,
adds main's safety connector, enhanced ArUco and stable-wait implementation/config,
then `prepare_sequential_deployment.py` stages PR #24's matched controller/plugins.
The traditional object_det package/config and reviewed det_color.py are materialized
in the same overlay. best.pt is checked against the main Git blob before reuse.

Server workspace: `/root/gpufree-data/stable-rc1-20261101/qualification_ws_rc1_build`.
The source payload is a verified file package, not a complete server Git clone.
EGO/sensors use the preserved underlay: 568 main-baseline files compared;
73 exact, 494 CRLF-only differences, one absent .gitattributes (not runtime code).
This establishes source/config correspondence, not a rebuilt EGO binary identity.

The initial 22-file release manifest was regenerated on the server and retrieved. Every
listed local file matches it. Expanded materialization and built-artifact manifests
remain in the workspace. The manifest is not a claim that the model or simulator
binaries were built from this repository.

## Initial validation (superseded by updates below)

- Independent ROS build succeeded; 11 plugin registrations and all stage trees passed.
- Offline suite: 156 passed, 2 failed, 0 skipped. Both failures require absent raw
  trial23b/c mission/model logs; they remain failures rather than manufactured fixtures.
- Isolated ROS: 14/14 passed with loaded-process checks.
- Live diagnostic: bt_ros and seven loaded libraries passed /proc executable/map identity.
- Live ROS values: EGO manager/max_vel, optimization/max_vel, bspline/limit_vel all 0.30;
  VisualServo forward=1.00, sprint=1.50, sprint_time=1.20. No simulator/safety tuning.

## Diagnostic 01 history, no formal-round credit

Run `20261102T0025_red_rc1_diag01` used the genuine candidate FM9G client. Five
natural-language stage requests were entered separately; each matched on the first
model generation and was confirmed only after the preceding terminal result.
Takeoff, cross_frame, detect_aruco (ID 35), and return_cross_frame succeeded.
The red-balloon request failed after its 50-second servo timeout (64.741 s including
navigation). The normal sixth stage was not executed in the failed session.
Explicit emergency_land succeeded and fresh MAVROS state proved armed=false.
Owned mission/SITL/render processes were then stopped; dead-PID lock was archived.

Rosbag replay: 240 object messages in the servo window, 126 qualifying red detections,
zero centered observations, no APPROACHING/SPRINT_START event. 2,500 setpoints show
zero horizontal velocity command in that window. Largest box ratio 0.4672 had
pixel error (172,-23); matching yaw was 2.4468, 0.6948 rad from pi, outside the
unchanged 0.45-rad red guard. This identifies the state-machine blockage; it does
not establish a reliable control fix, physical burst, wrong hit, or collision verdict.

Full rosbag: 6.2 GiB retained on server. Full camera video derived from the bag:
6,560 frames, 656 seconds, original source timestamps burned in; decode passed.
Desktop video is 597.8 seconds but scene windows were occluded and x11 capture
failed near the end after a desktop resize. It cannot prove the outside burst.
No motion code or gains were changed to make this failed run pass.

## Initial open gates (superseded by updates below)

- Review the real observation/control replay and preserve existing safety, speed,
  and red heading safeguards before choosing any narrowly supported correction.
- Prepare visible outside-view plus camera recording with resize/health checks.
- Recover missing historical fixtures; two upstream contact PNGs remain unavailable.
- Freeze a successful candidate and execute red/purple/blue three complete rounds each,
  with separate physical-hit/no-mis-hit evidence and normal return/disarm.
- Record final release commit, expanded deployment manifest and rollback instructions.
  Ask before any remote push, as AGENTS.md requires.

Rollback: after fresh disarm, stop only the candidate's owned graph and launch the
preserved old workspace using its original configuration. Do not restore sources
without rebuilding/restarting when a C++ artifact was changed.

## Deadzone candidate validation update

The minimal deadzone derivative-reset correction was independently built. Two real-source
C++ lifecycle/replay tests passed. The full server offline verifier reports 157 passed,
2 absent historical-log failures, 0 skipped; isolated ROS again passed 14/14 with live
process identity. A real PX4 takeoff, five-second hover and normal landing smoke passed
with final armed=false. This smoke used no model and earns no formal-round credit.
The earlier missing-rospy diagnosis was a wrapper PYTHONPATH error and is superseded.

X11 desktop capture misses the native Vulkan surface. Native observer-only RGB cameras
with distinct sensor IDs/ports passed an 80-frame-per-camera preflight; perception
camera configuration, physics, rendering options and flight parameters are unchanged.
Corrected-candidate diagnostic 20261102T0228_red_deadzone_diag02 completed all six
BT stages and normal landing/disarm. External native video confirms red burst, but
blue disappears at drone contact after a 7.660-second safety recovery. Purple remains
intact. One software boundary event and unresolved wall contact preclude acceptance.
Fourth model request required one rejected generation before the correct action.
No SPRINT_START occurred; hit terminal reason remains ATTEMPTED_UNVERIFIED.
All owned simulation/recording processes are stopped and lock archived. Formal credit
remains zero. This single randomized diagnostic cannot establish a causal repair or
three-color stability. Review post-hit hold/recovery before more live runs.

## Recovery-release candidate and diagnostic 03

The 24-file payload manifest now includes mavros_cnt.cpp/.h. It matches local
source hashes and diagnostic 03 preparation payloads. The preserved underlay is
unchanged; this is not a claim of a rebuilt EGO binary.

The narrowly scoped safety-release patch replaces an idle stale command with
current-position hold only if no upper-layer command revision changed during
recovery; active updates are retained. Independent build and plugin preflight
passed. All isolated ROS cases passed 16/16, each with bt_ros plus five mapped
libraries verified. Full offline suite: 157 passed, 2 absent historical raw-log
failures, 0 skipped.

Run 20261102T051012_red_recovery_diag03 completed six real FM9G stages, each
first-generation matched, separately confirmed and sent after the previous
terminal result. Execution sum 121.095 s; first acceptance to final terminal
326.621 s includes operator review and is not official contest timing.
The hit node reports SUCCESS/ATTEMPTED_UNVERIFIED. Independent native video
review confirms red contact, a transient pink particle, and persistent red
absence; blue and purple are present after normal landing/disarm.

Software boundary entries: zero. This flight did not exercise safety recovery
release, and its randomized scene is not a paired comparison against diag02.
Collision review remains unresolved because of occlusion and absent dedicated
contact telemetry. It receives no formal-round credit; acceptance remains 0/9.
Do not treat full video decode or sampled overview review as exhaustive collision
proof. Native odom twist is zero-filled and cannot be used as actual speed.

Both full observer videos and the PX4 ULog are retained locally with SHA-256
verification; the 8.6 GiB bag remains on server. All owned flight/capture
processes are stopped after fresh disarm; a residual owned RViz was also
terminated. Original raw cleanup is preserved with a separate local supplement;
SSH disconnected while appending the remote cleanup file, so that write is
unconfirmed. No commit or push was performed.

Rollback recovery-release only: restore mavros_cnt.cpp.before and mavros_cnt.h.before
from /root/gpufree-data/stable-rc1-20261101/backups/recovery-release-20261102/
to the independent workspace src/mission_pkg/src and include paths, rebuild
mission_pkg after sourcing Noetic and preserved underlay, then refreeze and
verify live executable/maps. Keep the original workspace and prior diagnostics.

## Blue diagnostics 04–06 and current candidate

After the server endpoint changed, the same recovery-release candidate was restored
and independently rebuilt. Its frozen runtime identities matched diagnostic 03;
567 available underlay files matched their prior byte-level archive. The new data
disk did not contain the old red03 bag, so historical server-retention statements
above must not be read as proof that this bag remains on the current instance.

Blue04 completed takeoff and cross-frame, then a simultaneous native-odom/camera
pause of approximately 1.246 s triggered the unchanged watchdog and AUTO.LAND.
No balloon-hit stage was run. Blue05 completed the first four stages and visually
confirmed a blue burst, but hit_balloon timed out at 68.201 s without SPRINT_START.
Normal return was blocked by recovery interlock; explicit emergency landing
succeeded and disarmed. Neither diagnostic earns formal credit.

Real blue05 input replay exposed continued approach movement while off-center.
The current `stable-rc1-approach-alignment-gate` candidate stops forward velocity
whenever approach alignment is lost; turning, altitude control, speed limits and
the red-specific near-loss completion guard remain unchanged. Real-source tests
passed 3/3; incremental mission_pkg build and plugin/tree preflight passed;
isolated ROS passed 16/16; offline suite reports 158 passed, 2 missing-log failures,
0 skipped. Replay verifies command gating, not improved closed-loop performance.

Blue06 still timed out after 68.855 s, without SPRINT_START. External video shows
contact and persistent blue absence but no captured burst particle. Red/purple
remain visible. The gate is therefore insufficient to resolve blue completion.
After hit failure, an 824.642 s idle preceded watchdog AUTO.LAND. Emergency input
to RUN took 1317.148 s; its later SUCCESS occurred after disarm and does not prove
a new descent. Bag/video coverage ended before that explicit confirmation.
Planning progress/obstacle errors and unresolved collision evidence are preserved.

All recorded owned flight processes are stopped and fresh armed=false was checked.
Server disk was about 99% full with less than 1 GB free; do not launch another
recorded run until storage and capture readiness are resolved. Preserve raw data.

Next, per the user: continue blue-focused offline review before another diagnostic;
do not rerun red merely to add attempts. Same-version red/purple/blue 3/3 remains
the eventual acceptance requirement. No results from different candidates are pooled.

See [work log and diagnostic reports](../reports/stable_rc1_20261102/README.md).
The user explicitly authorized GitHub publication of the current code in this chat.
This publication does not authorize merging the unqualified candidate into main.

