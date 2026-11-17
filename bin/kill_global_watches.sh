#!/bin/bash
# 2026-11-17 (Simon): deactivate URL-less global watches (nothing feeds them in simple mode),
# and keep every signup email forever in a contacts table (+ trigger) for future announcements.
set -e
DB=/var/lib/drop-watcher/dropwatcher.db; TS=$(date +%Y%m%d_%H%M%S)
sqlite3 "$DB" <<SQL
CREATE TABLE global_watch_backup_$TS AS SELECT id, email, active FROM watchers WHERE active=1 AND url='';
UPDATE watchers SET active=0 WHERE active=1 AND url='';
CREATE TABLE IF NOT EXISTS contacts (
  email TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, source TEXT DEFAULT 'watch_signup');
INSERT INTO contacts (email, first_seen, last_seen)
  SELECT lower(email), min(created), max(created) FROM watchers WHERE email!='' GROUP BY lower(email)
  ON CONFLICT(email) DO UPDATE SET last_seen=max(last_seen, excluded.last_seen);
CREATE TRIGGER IF NOT EXISTS contacts_on_watch_insert AFTER INSERT ON watchers
BEGIN
  INSERT INTO contacts (email, first_seen, last_seen)
    VALUES (lower(NEW.email), COALESCE(NEW.created, datetime('now')), COALESCE(NEW.created, datetime('now')))
    ON CONFLICT(email) DO UPDATE SET last_seen=excluded.last_seen;
END;
SELECT 'deactivated', count(*) FROM global_watch_backup_$TS;
SELECT 'active now', count(*) FROM watchers WHERE active=1;
SELECT 'contacts', count(*) FROM contacts;
SQL
echo "backup table: global_watch_backup_$TS"
