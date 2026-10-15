#!/usr/bin/env bash
# Deploy the 2026-10-15 rule-compliance files on the simulation server.
# Run ON THE SERVER from the directory the deploy files were uploaded to:
#   bash deploy_rule_compliance.sh            # deploy
#   bash /home/ubuntu/rule_compliance_backup_<ts>/restore.sh   # roll back
# Refuses to touch anything unless every live file has the reviewed MD5 and
# no formal trial is running. Restart the simulation environment afterwards.
#
# 2026-10-15: adds mission_prompt.txt (few-shot examples for phrasings that
# caused the LLM to over-generate; see patches/patch_mission_prompt_paraphrase_examples.py)
# and a new mission_once.py build with the matching single_action_problems()
# check (patches/patch_mission_publish_fallback.py v2). The server is expected
# to be at the rolled-back 2026-10-14 state (md5 4b0ae381...) for mission_once.py;
# if it is still at the previously-tried candidate (e7bb1627...) this script
# will refuse and tell you so -- do not loosen the expected-md5 check to force it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date +%Y%m%dT%H%M%S)"
BACKUP="/home/ubuntu/rule_compliance_backup_${TS}"

# name | live path | expected live md5 | new md5
FILES=(
  "mission_once.py|/home/ubuntu/model/mission_once.py|4b0ae381b683b7c38d30baf808ed1346|1597c5c139632fff4823e8b4d7cadd28"
  "mission_prompt.txt|/home/ubuntu/model/prompts/mission_prompt.txt|321f9b78eb3ad477172f37c70d8b921f|204b91245046f3d11ac342a5b229cc20"
  "aruco_detect_node.py|/home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py|0f15e84bdaed68c85d3b6b6ee5e33788|43c3bc40fc5c7de29730f5f1ce32574f"
  "det_color.py|/home/ubuntu/catkin_ws/src/object_det/scripts/det_color.py|9eda726899abaf4f951f6b03a08c11ad|348dd7d0ed3c66ce972c1e8158b3a07a"
)

if [ -d /tmp/tcei_formal_trial.lock ]; then
  echo "formal trial lock present; not deploying" >&2; exit 1
fi

for row in "${FILES[@]}"; do
  IFS='|' read -r name live old new <<<"$row"
  got_live="$(md5sum "$live" | cut -d' ' -f1)"
  got_new="$(md5sum "$HERE/$name" | cut -d' ' -f1)"
  [ "$got_live" = "$old" ] || { echo "$live md5 $got_live != expected $old; nothing changed" >&2; exit 1; }
  [ "$got_new" = "$new" ]  || { echo "$HERE/$name md5 $got_new != expected $new; upload corrupted?" >&2; exit 1; }
done

mkdir -p "$BACKUP"
{ echo '#!/usr/bin/env bash'; echo 'set -euo pipefail'; } > "$BACKUP/restore.sh"
for row in "${FILES[@]}"; do
  IFS='|' read -r name live old new <<<"$row"
  cp -p "$live" "$BACKUP/$name"
  echo "cp -p '$BACKUP/$name' '$live'; md5sum '$live'  # expect $old" >> "$BACKUP/restore.sh"
done
echo 'echo "restored; restart the simulation environment"' >> "$BACKUP/restore.sh"

for row in "${FILES[@]}"; do
  IFS='|' read -r name live old new <<<"$row"
  # cat > keeps the live file's owner and mode; the files are byte-checked above and below.
  cat "$HERE/$name" > "$live"
  [ "$(md5sum "$live" | cut -d' ' -f1)" = "$new" ] || { echo "post-copy md5 mismatch on $live; run $BACKUP/restore.sh" >&2; exit 1; }
  echo "deployed $live ($old -> $new)"
done
/opt/conda/envs/demo/bin/python3 -m py_compile /home/ubuntu/model/mission_once.py
echo "backup + restore.sh: $BACKUP"
echo "next: restart the simulation environment, then run the checks in v3_stability/rule_compliance/README.md"
