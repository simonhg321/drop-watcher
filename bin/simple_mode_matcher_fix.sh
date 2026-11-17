#!/bin/bash
# Simple-mode alert fix (2026-11-17). Reversible: backups in /var/lib/drop-watcher/backups.
#  1. DW_MATCHER fts5 -> blob in crontab (FTS5 index is empty for strict single-page user fetches)
#  2. clear stale 'maker' on listing-mode watches (retired prompt; now only suppresses matches)
#  3. drop the broken duplicate hgr-watch cron line (relative path, fails hourly)
set -e
TS=$(date +%Y%m%d_%H%M%S); DB=/var/lib/drop-watcher/dropwatcher.db
mkdir -p /var/lib/drop-watcher/backups
crontab -l > /var/lib/drop-watcher/backups/crontab.$TS.bak
crontab -l | sed 's/^DW_MATCHER=fts5$/DW_MATCHER=blob/' | grep -v 'python3 bin/poll.py' | crontab -
sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS watcher_maker_backup_$TS AS SELECT id, maker FROM watchers WHERE maker IS NOT NULL AND maker != '';
UPDATE watchers SET maker='' WHERE mode='listing' AND url != '' AND maker IS NOT NULL AND maker != '';"
echo "matcher: $(crontab -l | grep ^DW_MATCHER)"; echo "poll lines: $(crontab -l | grep -c poll.py)"
echo "makers cleared; backup table watcher_maker_backup_$TS, crontab backup /var/lib/drop-watcher/backups/crontab.$TS.bak"
