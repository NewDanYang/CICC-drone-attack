# 5.1 Presence-sweep flight gate

This package contains the Stage-A P11 replay variants requested by the Astra
handoff. It is an offline development-data evaluation of nine real 5 Hz
VisualServo windows (three red, three purple, three blue). Stage B was not
entered because the development gate failed.

The baseline is the existing 224/224 P10 replay. `p11_servo_replay.py` keeps
the same input contract and exposes one independent variant argument:

```text
base A1 A2 A3 A4
```

The four variants are:

* A1: 0.25 s verification, 1.2x crop, 40 px minimum, one negative drops to SEARCH.
* A2: scan-size lock with CSRT scale clamped to `[0.85, 1.6]`.
* A3: refresh interval reduced to 1.0 s.
* A4: train-only threshold fit `(0.5, 0.5, 0.4, 0.4)` from `p8_r224.jsonl`.

All YOLO references and image processing in this directory are offline scoring
or replay evidence. They are not runtime dependencies. No VisualServo, launch,
velocity, waypoint, mission, or competition model files were changed.

To reproduce on the research server, after copying `tools/p11_servo_replay.py`
to `/root/gpufree-data/fm_research/tools/`, run one variant at a time:

```bash
cd /root/gpufree-data/fm_research
/opt/conda/envs/demo/bin/python3 tools/p11_servo_replay.py evidence/p11_A1 224,224 \
  01_r1_red_baseline,04_r1_purple_baseline,05_r1_blue_baseline,08_r2_red_baseline,09_r2_purple_baseline,12_r2_blue_baseline,13_r3_red_baseline,16_r3_purple_baseline,17_r3_blue_baseline \
  fit_p8_448.json A1
```

Use `tools/score_p11.py` on the copied JSON directories to generate the gate
summary. The raw server archive SHA-256 is recorded in `evidence/server_manifest.json`.
