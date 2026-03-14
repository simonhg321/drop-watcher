#!/bin/bash
# migrate_dirs.sh — One-time migration to separate code/config/data/logs on ironman
# Run as shg: bash ~/drop-watcher/bin/migrate_dirs.sh
# HGR

set -euo pipefail

echo "=== Drop Watcher Directory Migration ==="
echo ""

# ── Create new directories ──────────────────────────────────────────────────
echo "[1/6] Creating directories..."
sudo mkdir -p /etc/drop-watcher
sudo mkdir -p /var/lib/drop-watcher
sudo mkdir -p /var/log/drop-watcher

# ── Move config + secrets ───────────────────────────────────────────────────
echo "[2/6] Moving config + secrets to /etc/drop-watcher/..."
sudo cp ~/drop-watcher/.env /etc/drop-watcher/.env
sudo cp ~/drop-watcher/config/sources.yaml /etc/drop-watcher/
sudo cp ~/drop-watcher/config/makers.yaml /etc/drop-watcher/
sudo cp ~/drop-watcher/config/cool_list.yaml /etc/drop-watcher/
sudo cp ~/drop-watcher/config/settings.yaml /etc/drop-watcher/

# ── Move data (PII + runtime state) ────────────────────────────────────────
echo "[3/6] Moving data to /var/lib/drop-watcher/..."
[ -f ~/drop-watcher/config/watchers.json ] && sudo cp ~/drop-watcher/config/watchers.json /var/lib/drop-watcher/
[ -f ~/drop-watcher/logs/seen_items.json ] && sudo cp ~/drop-watcher/logs/seen_items.json /var/lib/drop-watcher/
[ -f ~/drop-watcher/logs/seen_content.json ] && sudo cp ~/drop-watcher/logs/seen_content.json /var/lib/drop-watcher/
[ -f ~/drop-watcher/logs/seen_feeds.json ] && sudo cp ~/drop-watcher/logs/seen_feeds.json /var/lib/drop-watcher/
[ -f ~/drop-watcher/logs/watchdog_state.json ] && sudo cp ~/drop-watcher/logs/watchdog_state.json /var/lib/drop-watcher/

# ── Move logs ───────────────────────────────────────────────────────────────
echo "[4/6] Moving logs to /var/log/drop-watcher/..."
sudo cp ~/drop-watcher/logs/*.log /var/log/drop-watcher/ 2>/dev/null || true
sudo cp ~/drop-watcher/logs/*.jsonl /var/log/drop-watcher/ 2>/dev/null || true

# ── Set permissions ─────────────────────────────────────────────────────────
echo "[5/6] Setting permissions..."
# Config: root owns, shg can read
sudo chown -R root:shg /etc/drop-watcher
sudo chmod 750 /etc/drop-watcher
sudo chmod 640 /etc/drop-watcher/*
# .env extra tight
sudo chmod 600 /etc/drop-watcher/.env

# Data: shg owns, nobody else reads
sudo chown -R shg:shg /var/lib/drop-watcher
sudo chmod 700 /var/lib/drop-watcher
sudo chmod 600 /var/lib/drop-watcher/*

# Logs: shg owns
sudo chown -R shg:shg /var/log/drop-watcher
sudo chmod 750 /var/log/drop-watcher
sudo chmod 640 /var/log/drop-watcher/*

# ── Update logrotate to new path ───────────────────────────────────────────
echo "[6/6] Updating logrotate..."
sudo tee /etc/logrotate.d/drop-watcher > /dev/null << 'LOGROTATE'
/var/log/drop-watcher/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

echo ""
echo "=== Migration complete ==="
echo ""
echo "Set these env vars in /etc/drop-watcher/.env (add to bottom):"
echo "  DW_CONFIG_DIR=/etc/drop-watcher"
echo "  DW_DATA_DIR=/var/lib/drop-watcher"
echo "  DW_LOG_DIR=/var/log/drop-watcher"
echo "  DW_ENV_FILE=/etc/drop-watcher/.env"
echo ""
echo "Then restart services:"
echo "  sudo supervisorctl restart all"
echo ""
echo "Verify with: python3 -c 'import paths; print(paths.CONFIG_DIR, paths.DATA_DIR, paths.LOG_DIR)'"
