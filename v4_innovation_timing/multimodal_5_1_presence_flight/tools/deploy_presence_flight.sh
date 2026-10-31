#!/usr/bin/env bash
set -euo pipefail
echo "Stage B was not approved: Stage-A development gate failed. No runtime deployment performed."
exit 2
