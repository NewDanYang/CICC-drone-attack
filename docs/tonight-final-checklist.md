# Final-night checklist (2026-11-02): freeze the YOLO baseline, verify, package

> **Correction (20:40):** the 30811 server runs the **official demo** (`bt_ros.cpp` `f3883b30…`,
> `visual_servo.cpp` `a97f5af2…`), not the team's sealed best build (`bt_ros.cpp` `9b1cefe9…`,
> 8/9 target balloons). Follow **`docs/WINNING_PLAN_20261102.md` §2 Steps 1–3** first: identify
> the build on the judged machine and, if time allows (≥ 2 h), deploy the sealed build with
> rollback and 3 trials. The MD5s in step 1 below describe the *official demo*; only freeze them
> if you decide to keep that build.

Decision: **no FM9G perception deployment tonight.** The FM9G bonus needs every target class
recognised by FM9G (FAQ "需要全部识别"); zero-shot FM9G localisation failed (round 3: frame 0/104,
marker 0/11) and FM9G balloon hitting is 0/11. Mixing with YOLO earns no bonus. The baseline is
proven and on disk now.

## For the SSH agent (server 30811; password from the user, never written down)

1. **Do not modify anything** under `/home/ubuntu/model` or `/home/ubuntu/catkin_ws`. Verify:
   ```
   md5sum /home/ubuntu/model/mission_once.py                                   # dcc050dd1daa1792a7312345932d0fcb
   md5sum /home/ubuntu/catkin_ws/src/mission_pkg/src/bt_ros.cpp                # f3883b30c69f3bdc248d50ac9fc0ad9e
   md5sum /home/ubuntu/catkin_ws/src/object_det/config/detection_params.yaml   # 3590c240ecfbc180f4c98b105c540ae8
   ```
   If any differs, stop and report.
2. **Confidence trials** (as many as time allows, priority order red → blue → purple, 2–3 each):
   full environment restart (`AGENTS.md` §2.3) → `run_formal_trial.sh <colour>`. Record per trial:
   colour, each stage pass/fail, total time, collisions, failure class (environment / command
   generation / algorithm). A command-generation miss (no command block, ends in <20 s) is
   re-run, not counted as an algorithm failure.
3. **Rule items to confirm on screen during one trial** (screenshot each):
   - YOLO detection window and ArUco window visible during the frame/QR stages (rule 4.4(5): no
     window = −5).
   - `rostopic echo /mavros/setpoint_raw/local` shows continuously changing values in flight.
4. Leave the server on the baseline with the simulator ready for the demo; report MD5s again.

## For the team

- Enter the official prompts **one step at a time** (rule: no one-click script).
- Submission package 「赛道_队伍名称_单位_联系方式」: source code (the deployed baseline as on the
  server), technical report, defence PPT.
- If asked about 九格多模态: FM9G performs the mandatory language → command parsing; we are **not**
  claiming the 10-point multimodal recognition bonus. Do not claim it — reviewers check source.
- v8 (`research/fm9g-v8-scene-perception`) stays out of the submission or is labelled research only.
