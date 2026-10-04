#!/usr/bin/env bash
# Soft-delete (unpublish) Skipper public posts by uuid. Rows stay in the DB
# (deleted_at set); reversible with:
#   UPDATE posts SET deleted_at=NULL WHERE uuid='<uuid>';
# Usage: bin/skipper_unpublish.sh <uuid-list-file> [reason]
# Takes a DB backup to /var/lib/skipper/backups/ first. Logs each row to audit_log.
# After running, the */10 cron gen_public_blog.py prunes the static /posts/ pages,
# or run it by hand: python3 bin/gen_public_blog.py
set -euo pipefail
LIST=${1:?uuid list file}; REASON=${2:-"public blog cleanup"}
DB=/var/lib/skipper/skipper.db
TS=$(date +%Y%m%d-%H%M%S)
sudo -u skipper mkdir -p /var/lib/skipper/backups
sudo -u skipper sqlite3 "$DB" ".backup /var/lib/skipper/backups/skipper-pre-unpub-$TS.db"
echo "backup: /var/lib/skipper/backups/skipper-pre-unpub-$TS.db"
{
  echo "BEGIN;"
  while read -r u; do
    [[ "$u" =~ ^[0-9a-f-]{36}$ ]] || continue
    echo "INSERT INTO audit_log(org_id,action,target_id,details_json) SELECT org_id,'post.unpublish',id,json_object('uuid',uuid,'reason','$REASON','by','ironman') FROM posts WHERE uuid='$u' AND deleted_at IS NULL;"
    echo "UPDATE posts SET deleted_at=strftime('%s','now'), updated_at=strftime('%s','now') WHERE uuid='$u' AND deleted_at IS NULL;"
  done < "$LIST"
  echo "COMMIT;"
} | sudo -u skipper sqlite3 "$DB"
echo "processed $(grep -cE '^[0-9a-f-]{36}$' "$LIST") uuids"
sudo -u skipper sqlite3 "$DB" "select count(*) as live_public_posts from posts where deleted_at is null;"
