#!/bin/bash
# sync_ironman.sh — run on ironman AFTER shipping from mac
# Usage: bash ~/drop-watcher/bin/sync_ironman.sh
#
# HGR — 2026-03-15

set -e

echo "=== 1. Deploy html/ to /var/www/html/ ==="
cp ~/drop-watcher/html/*.html /var/www/html/
cp ~/drop-watcher/html/favicon.svg /var/www/html/
cp ~/drop-watcher/html/robots.txt /var/www/html/
cp ~/drop-watcher/html/sitemap.xml /var/www/html/
echo "  done"

echo ""
echo "=== 2. Remove dead files from ~/drop-watcher/ ==="
rm -f ~/drop-watcher/orchestrator.py
rm -f ~/drop-watcher/watcher_status.html
rm -f ~/drop-watcher/test-escape.py
rm -f ~/drop-watcher/.cleanup.sh
rm -f ~/drop-watcher/instockornot_zone.txt
rm -f ~/drop-watcher/gunicorn.ctl
# HTML files now live in html/
rm -f ~/drop-watcher/index.html
rm -f ~/drop-watcher/watchlist.html
rm -f ~/drop-watcher/my-alerts.html
rm -f ~/drop-watcher/get-my-link.html
rm -f ~/drop-watcher/privacy.html
rm -f ~/drop-watcher/alerts.html
rm -f ~/drop-watcher/status.html
rm -f ~/drop-watcher/hgr.html
# Scripts moved to bin/
rm -f ~/drop-watcher/check_users.sh
rm -f ~/drop-watcher/nuke_watchers.sh
echo "  done"

echo ""
echo "=== 3. Remove dead files from /var/www/html/ ==="
rm -f /var/www/html/all_the_things.html
rm -f /var/www/html/terms.html
rm -f /var/www/html/watcher_status.html
echo "  done"

echo ""
echo "=== 4. Remove stale dirs from ~/drop-watcher/ ==="
rm -rf ~/drop-watcher/logs/
rm -rf ~/drop-watcher/data/
rm -rf ~/drop-watcher/__pycache__/
rm -rf ~/drop-watcher/agents/logs/
rm -rf ~/drop-watcher/agents/__pycache__/
echo "  done"

echo ""
echo "=== 5. Clean up bin/ ==="
rm -f ~/drop-watcher/bin/drop-watcher.conf
rm -f ~/drop-watcher/bin/index.html
rm -f ~/drop-watcher/bin/nuke_watchers.sh
rm -f ~/drop-watcher/bin/restart_stuff.sh
echo "  done"

echo ""
echo "=== 6. Remove stale config/watchers.json ==="
rm -f ~/drop-watcher/config/watchers.json
rm -f ~/drop-watcher/config/watchers.json.lock
echo "  (real watchers.json is in /var/lib/drop-watcher/)"
echo "  done"

echo ""
echo "=== 7. Remove stale .env ==="
rm -f ~/drop-watcher/.env
echo "  (real .env is in /etc/drop-watcher/)"
echo "  done"

echo ""
echo "=== 8. Update supervisor conf and reload ==="
sudo cp ~/drop-watcher/conf/drop-watcher.conf /etc/supervisor/conf.d/drop-watcher.conf
sudo supervisorctl reread
sudo supervisorctl update
echo "  done"

echo ""
echo "=== 9. Verify ==="
echo "--- supervisorctl ---"
sudo supervisorctl status
echo ""
echo "--- gunicorn workers ---"
ps aux | grep gunicorn | grep -v grep
echo ""
echo "--- ~/drop-watcher ---"
ls ~/drop-watcher/
echo ""
echo "--- /var/www/html ---"
ls /var/www/html/

echo ""
echo "=== SYNC COMPLETE ==="
