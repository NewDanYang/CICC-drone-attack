#!/usr/bin/env bash
set -o pipefail
base=/home/ubuntu/tcei_baseline_tools/results/formal_trials
for d in $(ls -d "$base"/20261101T20*_A0 2>/dev/null | sort); do
  name=$(basename "$d")
  color=$(printf '%s' "$name" | sed -E 's/^20261101T[0-9]+_([^_]+)_A0$/\1/')
  mission="$d/mission_once.out"
  observer="$d/observer.out"
  audit=$(sed -n 's/.*evidence=\([^ ]*\).*/\1/p' "$mission" 2>/dev/null | head -1)
  audit_ok=0
  images_ok=0
  [ -f "$audit/audit.jsonl" ] && audit_ok=1
  [ -d "$audit/images" ] && images_ok=1
  raw=$(find "$d/logs" -maxdepth 1 -type f -name '*.jsonl' -print 2>/dev/null | sort | head -1)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$color" "$d" "$audit" "$audit_ok" "$images_ok" "$raw"
done
