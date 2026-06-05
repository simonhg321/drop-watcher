#!/usr/bin/env bash
# fix_log_mgmt.sh — add logrotate coverage for preflight.jsonl and reclaim its space.
#
# Why: /etc/logrotate.d/drop-watcher only matches *.log, so preflight.jsonl
# (hourly diagnostic, ~65KB/entry) grows unbounded — it hit 108MB. This installs
# a targeted rule (preflight.jsonl is diagnostic-only, safe to copytruncate) and
# trims the live file now, keeping the most recent entries.
#
# Run as root:  sudo bash /home/shg/drop-watcher/bin/fix_log_mgmt.sh
# Idempotent — safe to re-run.
set -euo pipefail

LOG_DIR=/var/log/drop-watcher
PF=$LOG_DIR/preflight.jsonl
ROTATE_CONF=/etc/logrotate.d/drop-watcher-preflight
KEEP_LINES=500

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo bash $0)" >&2
  exit 1
fi

echo "[1/3] Installing logrotate rule -> $ROTATE_CONF"
cat > "$ROTATE_CONF" <<'EOF'
/var/log/drop-watcher/preflight.jsonl {
    weekly
    rotate 2
    compress
    missingok
    notifempty
    copytruncate
}
EOF
chmod 644 "$ROTATE_CONF"

echo "[2/3] Reclaiming space (keep last $KEEP_LINES entries, preserve owner/perms)"
if [[ -f "$PF" ]]; then
  before=$(du -h "$PF" | cut -f1)
  owner=$(stat -c '%U:%G' "$PF")
  mode=$(stat -c '%a' "$PF")
  tail -n "$KEEP_LINES" "$PF" > "$PF.tmp"
  cat "$PF.tmp" > "$PF"          # truncate-in-place: keeps inode, owner, perms
  rm -f "$PF.tmp"
  chown "$owner" "$PF"; chmod "$mode" "$PF"
  echo "    $PF: $before -> $(du -h "$PF" | cut -f1)"
else
  echo "    $PF not found — skipping trim"
fi

echo "[3/3] Validating rule (dry-run, no action)"
logrotate -d "$ROTATE_CONF" 2>&1 | grep -iE 'considering|rotating|copytruncate|error' || true

echo "DONE."
