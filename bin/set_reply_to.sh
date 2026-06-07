#!/usr/bin/env bash
# set_reply_to.sh — point all Drop Watcher outbound reply-to at one address.
# ALERT_TO drives REPLY_TO for every customer alert/verification email.
# Backs up .env, collapses any duplicate ALERT_TO lines to a single value,
# verifies, then restarts web_watcher so the Flask app picks it up.
#
# Usage:  sudo bin/set_reply_to.sh [address]   (default: info@instockornot.club)
set -euo pipefail

ADDR="${1:-info@instockornot.club}"
F=/etc/drop-watcher/.env
STAMP="$(date +%F-%H%M)"

[ -f "$F" ] || { echo "✗ $F not found — ABORT"; exit 1; }

echo "=== 1. Backup ==="
cp -p "$F" "$F.bak-$STAMP" && echo "  ✓ $F.bak-$STAMP"

echo "=== 2. Set ALERT_TO=$ADDR (drop all old ALERT_TO lines, write one) ==="
sed -i "/^ALERT_TO=/d" "$F"
printf 'ALERT_TO=%s\n' "$ADDR" >> "$F"

echo "=== 3. Verify ==="
grep -nE '^ALERT_TO=' "$F"
COUNT="$(grep -cE '^ALERT_TO=' "$F")"
[ "$COUNT" = "1" ] || { echo "  ✗ expected 1 ALERT_TO line, found $COUNT — check $F"; exit 1; }

echo "=== 4. Restart web_watcher ==="
supervisorctl restart web_watcher
sleep 2
supervisorctl status web_watcher

echo ""
echo "DONE ✓  reply-to → $ADDR   (backup: $F.bak-$STAMP)"
