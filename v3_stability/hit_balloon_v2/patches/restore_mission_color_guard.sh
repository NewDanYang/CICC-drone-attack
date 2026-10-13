#!/usr/bin/env bash
set -euo pipefail
target=/home/ubuntu/model/mission_once.py
backup=/home/ubuntu/mission_color_guard_backup_20261012T1850/mission_once.py
test ! -e /tmp/tcei_formal_trial.lock || { echo 'formal trial active' >&2; exit 7; }
test "$(md5sum "$target" | awk '{print $1}')" = 4b0ae381b683b7c38d30baf808ed1346
test "$(md5sum "$backup" | awk '{print $1}')" = dcc050dd1daa1792a7312345932d0fcb
cp -p "$backup" "$target"
md5sum "$target"
