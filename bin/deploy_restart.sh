#!/usr/bin/env bash
# deploy_restart.sh — restart the drop-watcher services that run from the repo so
# they pick up freshly committed code. Use after pulling/committing changes that
# touch the scraper (web_watcher) or the Flask app (watcher_signup).
#
#   web_watcher    — scraper; restart to capture linkpick product candidates on drops
#   watcher_signup — gunicorn web app; restart for verify/watch-create backfill hooks
#   (cron per_user_alerter needs no restart — it runs fresh from the repo each cycle)
#
# Usage:  sudo bin/deploy_restart.sh
set -euo pipefail

echo "=== git HEAD ==="
git -C /home/shg/drop-watcher log --oneline -1 || true

echo "=== restart web_watcher + watcher_signup ==="
supervisorctl restart web_watcher watcher_signup
sleep 3
supervisorctl status web_watcher watcher_signup

echo ""
echo "DONE ✓  new code is live. web_watcher will now write link_candidates on new drops;"
echo "        signup verify + new-watch creation now fire the 'what we know' backfill."
