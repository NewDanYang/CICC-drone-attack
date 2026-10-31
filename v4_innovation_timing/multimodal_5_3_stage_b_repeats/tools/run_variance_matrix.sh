#!/usr/bin/env bash
set -u

STAGE_B="${1:?isolated stage-B source directory}"
ROOT="${2:?recording root}"
OUT="${3:?output directory}"
PYTHON="${PYTHON:-/opt/conda/envs/demo/bin/python3}"
VALIDATOR="${VALIDATOR:-$STAGE_B/tools/validate_runtime_vs_truth.py}"
mkdir -p "$OUT/rounds" "$OUT/audits"

run_group() {
    local label="$1"
    local runs="$2"
    local result="$OUT/rounds/${label}.json"
    local log="$OUT/rounds/${label}.stdout.log"
    set +e
    "$PYTHON" "$VALIDATOR" "$STAGE_B" "$ROOT" "$runs" "$result" "$label" >"$log" 2>&1
    local rc=$?
    set -e
    if [[ ! -s "$result" ]]; then
        python3 - "$result" "$label" "$rc" "$log" <<'PY'
import json, sys
out, label, rc, log = sys.argv[1:]
json.dump({'label': label, 'status': 'crashed', 'exit_code': int(rc),
           'log': log}, open(out, 'w'), indent=1)
PY
    fi
    # Preserve every per-run audit directory, including runs that ended with
    # an inference error.  The validator uses the label in each directory so
    # repeated runs never overwrite one another.
    cp -a /tmp/p12e_runtime_truth/${label}_* "$OUT/audits/" 2>/dev/null || true
    echo "GROUP label=$label rc=$rc runs=$runs"
}

# 45 core runs: one canonical order followed by four independently shuffled
# orders. Each group is a fresh Python process/model load.
run_group round01_canonical \
  "01_r1_red_baseline,04_r1_purple_baseline,05_r1_blue_baseline,08_r2_red_baseline,09_r2_purple_baseline,12_r2_blue_baseline,13_r3_red_baseline,16_r3_purple_baseline,17_r3_blue_baseline"
run_group round02_shuffled \
  "13_r3_red_baseline,05_r1_blue_baseline,16_r3_purple_baseline,01_r1_red_baseline,12_r2_blue_baseline,08_r2_red_baseline,17_r3_blue_baseline,04_r1_purple_baseline,09_r2_purple_baseline"
run_group round03_shuffled \
  "09_r2_purple_baseline,17_r3_blue_baseline,04_r1_purple_baseline,13_r3_red_baseline,08_r2_red_baseline,01_r1_red_baseline,16_r3_purple_baseline,05_r1_blue_baseline,12_r2_blue_baseline"
run_group round04_shuffled \
  "12_r2_blue_baseline,08_r2_red_baseline,01_r1_red_baseline,17_r3_blue_baseline,05_r1_blue_baseline,04_r1_purple_baseline,09_r2_purple_baseline,16_r3_purple_baseline,13_r3_red_baseline"
run_group round05_shuffled \
  "04_r1_purple_baseline,16_r3_purple_baseline,13_r3_red_baseline,09_r2_purple_baseline,01_r1_red_baseline,17_r3_blue_baseline,08_r2_red_baseline,12_r2_blue_baseline,05_r1_blue_baseline"

# Controlled same-case group: five repetitions of one recorded game in one
# fresh process, preserving the repeated-order condition explicitly.
run_group same_case_01_x5 \
  "01_r1_red_baseline,01_r1_red_baseline,01_r1_red_baseline,01_r1_red_baseline,01_r1_red_baseline"

echo "MATRIX_COMPLETE"
