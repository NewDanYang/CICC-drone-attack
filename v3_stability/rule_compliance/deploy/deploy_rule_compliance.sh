#!/usr/bin/env bash
# Deploy the 2026-10-15 rule-compliance files on the simulation server.
# Run ON THE SERVER from the directory the deploy files were uploaded to:
#   bash deploy_rule_compliance.sh            # deploy
#   bash /home/ubuntu/rule_compliance_backup_<ts>/restore.sh   # roll back
# Refuses to touch anything unless every live file has the reviewed MD5 and
# no formal trial is running. Restart the simulation environment afterwards.
#
# 2026-10-15 (v3): mission_once.py only, fixing the fallback-ranking bug the
# real-model verification found (patches/patch_mission_publish_fallback.py
# v3 -- see its docstring for the distractor_color repro). mission_prompt.txt,
# aruco_detect_node.py and det_color.py have NO changes this round; the
# server is expected to already have them at the v2 candidate MD5s below
# (Astra's 2026-10-15 "Verify rule compliance v2 paraphrases" run left the
# v2 candidate deployed rather than rolling back). If the live mission_once.py
# is still at the pre-v2 rolled-back state (4b0ae381...) instead, this script
# will refuse and tell you so -- do not loosen the expected-md5 check to
# force it; confirm which state the server is actually in first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date +%Y%m%dT%H%M%S)"
BACKUP="/home/ubuntu/rule_compliance_backup_${TS}"

# name | live path | expected live md5 | new md5
FILES=(
  "mission_once.py|/home/ubuntu/model/mission_once.py|1597c5c139632fff4823e8b4d7cadd28|fca24bf1142ca8cddfb9e8d39c387a43"
  "mission_prompt.txt|/home/ubuntu/model/prompts/mission_prompt.txt|204b91245046f3d11ac342a5b229cc20|204b91245046f3d11ac342a5b229cc20"
  "aruco_detect_node.py|/home/ubuntu/catkin_ws/src/mission_pkg/scripts/aruco_detect_node.py|43c3bc40fc5c7de29730f5f1ce32574f|43c3bc40fc5c7de29730f5f1ce32574f"
  "det_color.py|/home/ubuntu/catkin_ws/src/object_det/scripts/det_color.py|348dd7d0ed3c66ce972c1e8158b3a07a|348dd7d0ed3c66ce972c1e8158b3a07a"
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
