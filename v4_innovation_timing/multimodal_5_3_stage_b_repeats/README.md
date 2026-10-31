# Stage B variance repeats

This package repeats the real `PerceptionBridge` over the recorded 2026-10-26 RGB frames and scores its published boxes directly against the recorded YOLO annotations. The runtime path itself contains only FM9G4B-V; truth is consumed by the offline scoring script after the bridge closes.

`v2/presence.py` adds CUDA event timing and allocated-memory audit fields. The matrix runner executes 45 core trials in five process-isolated order groups, then controlled same-case repetitions. See `REPORT.md` for the fixed sample list, raw evidence paths, and the Stage C decision.
