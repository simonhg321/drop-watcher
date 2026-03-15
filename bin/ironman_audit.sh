#!/bin/bash
# ironman_audit.sh — snapshot of ironman's state
# Run on ironman: bash ~/drop-watcher/bin/ironman_audit.sh

echo "=== ~/drop-watcher ==="
ls -la ~/drop-watcher/

echo ""
echo "=== ~/drop-watcher/agents ==="
ls -la ~/drop-watcher/agents/ 2>/dev/null

echo ""
echo "=== ~/drop-watcher/bin ==="
ls -la ~/drop-watcher/bin/ 2>/dev/null

echo ""
echo "=== ~/drop-watcher/config ==="
ls -la ~/drop-watcher/config/ 2>/dev/null

echo ""
echo "=== ~/drop-watcher/conf ==="
ls -la ~/drop-watcher/conf/ 2>/dev/null

echo ""
echo "=== ~/drop-watcher/web ==="
ls -la ~/drop-watcher/web/ 2>/dev/null

echo ""
echo "=== ~/drop-watcher/html ==="
ls -la ~/drop-watcher/html/ 2>/dev/null

echo ""
echo "=== /var/www/html ==="
ls -la /var/www/html/

echo ""
echo "=== /var/www/html/stats ==="
ls -la /var/www/html/stats/ 2>/dev/null

echo ""
echo "=== /etc/drop-watcher ==="
ls -la /etc/drop-watcher/ 2>/dev/null

echo ""
echo "=== /var/lib/drop-watcher ==="
ls -la /var/lib/drop-watcher/ 2>/dev/null

echo ""
echo "=== /var/log/drop-watcher ==="
ls -la /var/log/drop-watcher/ 2>/dev/null

echo ""
echo "=== /etc/supervisor/conf.d ==="
ls -la /etc/supervisor/conf.d/ 2>/dev/null

echo ""
echo "=== crontab ==="
crontab -l

echo ""
echo "=== supervisorctl ==="
sudo supervisorctl status

echo ""
echo "=== gunicorn workers ==="
ps aux | grep gunicorn | grep -v grep
