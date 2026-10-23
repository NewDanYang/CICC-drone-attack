#!/usr/bin/env bash
# Capture OpenCV windows during one formal flight without changing focus.
set -uo pipefail
out="${1:?usage: capture_windows.sh output_directory}"
mkdir -p "$out"
export DISPLAY=:20 XAUTHORITY=/home/ubuntu/.Xauthority
seen_lock=0
for i in $(seq -w 1 100); do
  if [[ -d /tmp/tcei_formal_trial.lock ]]; then seen_lock=1; fi
  if [[ "$seen_lock" == 1 && ! -d /tmp/tcei_formal_trial.lock ]]; then break; fi
  printf '%s ' "$(date -Is)" >> "$out/capture_index.txt"
  wmctrl -l | grep -Ei 'Detection|ArUco' >> "$out/capture_index.txt" || true
  for spec in 'Detection + Color|detection' 'ArUco Detection (Python)|aruco'; do
    title="${spec%%|*}"
    label="${spec##*|}"
    id="$(wmctrl -l | grep -F "$title" | tail -1 | awk '{print $1}')"
    if [[ -n "$id" ]]; then
      if xwd -silent -id "$id" -out "$out/.capture_${label}.xwd" 2>/dev/null; then
        ffmpeg -hide_banner -loglevel error -y -i "$out/.capture_${label}.xwd" \
          -frames:v 1 "$out/${label}_${i}.png" 2>>"$out/capture_errors.txt" || true
      fi
    fi
  done
  sleep 2
done
rm -f "$out/.capture_detection.xwd" "$out/.capture_aruco.xwd"
echo "capture_complete=$(date -Is)" >> "$out/capture_index.txt"
