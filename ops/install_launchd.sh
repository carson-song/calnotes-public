#!/bin/bash
# Install (or reinstall) the two scheduled jobs for the logged-in user. Run from the repo root:
#   ops/install_launchd.sh
# Reads the settings below from your environment; set them first (see ops/MAC_MINI.md).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${CALNOTES_PYTHON:-$REPO/.venv/bin/python}"
for v in CALNOTES_DIGEST_TO CALNOTES_PLANS_ACCOUNT CALNOTES_NOTES_ACCOUNT; do
  [ -n "${!v:-}" ] || { echo "Set $v first"; exit 1; }
done
[ -x "$PYTHON" ] || { echo "No Python at $PYTHON (make the venv, or set CALNOTES_PYTHON)"; exit 1; }
mkdir -p "$REPO/runs/logs" "$HOME/Library/LaunchAgents"
for job in digest replies; do
  src="$REPO/ops/launchd/com.calnotes.$job.plist"
  dst="$HOME/Library/LaunchAgents/com.calnotes.$job.plist"
  hc_var="CALNOTES_HC_$(echo $job | tr a-z A-Z)"
  sed -e "s#__PYTHON__#$PYTHON#g" -e "s#__REPO__#$REPO#g" \
      -e "s#__DIGEST_TO__#$CALNOTES_DIGEST_TO#g" -e "s#__PLANS_ACCOUNT__#$CALNOTES_PLANS_ACCOUNT#g" \
      -e "s#__NOTES_ACCOUNT__#$CALNOTES_NOTES_ACCOUNT#g" -e "s#__HC_[A-Z]*__#${!hc_var:-}#g" "$src" > "$dst"
  plutil -lint "$dst" >/dev/null
  launchctl bootout "gui/$(id -u)" "$dst" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dst"
  echo "loaded com.calnotes.$job"
done
echo "Check with: launchctl print gui/$(id -u)/com.calnotes.replies | grep -E 'state|last exit'"
