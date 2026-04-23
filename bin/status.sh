#!/bin/bash
# Quick health + activity check. Run on ironman when checking in.
set -u

DB="${DW_DB:-/var/lib/drop-watcher/dropwatcher.db}"
SITE="${DW_SITE:-https://instockornot.club}"

hr() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

hr "Site"
for path in / /blog.html; do
    read -r code time < <(curl -s -o /dev/null -w '%{http_code} %{time_total}' "${SITE}${path}")
    printf '  %-12s %s  %ss\n' "$path" "$code" "$time"
done

hr "Watchers"
sqlite3 "$DB" <<'SQL'
.mode column
.headers on
SELECT
  COUNT(*)                                                              AS total,
  SUM(active)                                                           AS active,
  SUM(CASE WHEN created >= datetime('now','-1 day')  THEN 1 ELSE 0 END) AS new_24h,
  SUM(CASE WHEN created >= datetime('now','-7 days') THEN 1 ELSE 0 END) AS new_7d
FROM watchers;
SQL

hr "New signups (7d)"
sqlite3 -column -header "$DB" "
SELECT substr(created,1,16) AS created,
       email,
       CASE active WHEN 1 THEN 'on' ELSE 'pending' END AS status,
       substr(keywords,1,40) AS keywords
FROM watchers
WHERE created >= datetime('now','-7 days')
ORDER BY created DESC;"

hr "Alerts fired"
sqlite3 -column -header "$DB" "
SELECT
  SUM(CASE WHEN sent_at >= datetime('now','-1 day')  THEN 1 ELSE 0 END) AS last_24h,
  SUM(CASE WHEN sent_at >= datetime('now','-7 days') THEN 1 ELSE 0 END) AS last_7d,
  COUNT(DISTINCT CASE WHEN sent_at >= datetime('now','-7 days') THEN recipient END) AS recipients_7d
FROM alert_tracking;"

hr "Recent alerts (last 10)"
sqlite3 -column -header "$DB" "
SELECT substr(sent_at,1,16) AS sent, alert_type AS type, recipient
FROM alert_tracking
ORDER BY sent_at DESC LIMIT 10;"

hr "Recent drops (last 5)"
sqlite3 -column -header "$DB" "
SELECT substr(timestamp,1,16) AS ts, priority AS pri, source, substr(page_summary,1,60) AS summary
FROM drops
ORDER BY timestamp DESC LIMIT 5;"
