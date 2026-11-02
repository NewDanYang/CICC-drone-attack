# Stable RC1 candidate snapshot — 2026-11-02

This records the candidate before its first GitHub publication. Status fields about
uncommitted/unpushed changes describe that capture time, not a later branch state.

Latest candidate: `stable-rc1-approach-alignment-gate`. Independent build and plugin
preflight passed; isolated ROS 16/16, real-source VisualServo tests 3/3, offline
158 passed / 2 failed / 0 skipped. The two failures still require absent original
trial23b/c logs. These checks were already run on the exact source hashes; publishing
this snapshot does not constitute a new flight or a new qualification result.

Six diagnostics were recorded across different candidates. Latest blue diag06
timed out after contact and persistent disappearance; no burst particle was captured.
Its long idle and emergency-confirmation delays, watchdog landing, incomplete
recording coverage and low disk space are documented without qualification credit.
Formal acceptance remains **0/9**. Purple target missions remain untested.

[Work log](Stable_RC1对话与工作日志.md) · [Current status](当前进度.md) ·
[Requirements](任务要求.md) · [Latest diagnostic](蓝色候选诊断06.md)

Raw bags, videos, ULogs, screenshots, local scratch and credentials are not included
in this source snapshot. Historical report links to those files refer to evidence
held locally or on the server, with the availability limits recorded in the log.
The GitHub branch is a reviewable candidate backup, not an accepted release.
