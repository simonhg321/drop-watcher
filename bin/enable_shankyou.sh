#!/usr/bin/env bash
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#
# enable_shankyou.sh — one-shot root steps for /go_shankyou/ click attribution:
#   1. Apache: proxy /go_shankyou/ and /sharp/ to gunicorn (5001)
#   2. configtest + graceful reload
#   3. restart watcher_signup so the new routes load
# Run: sudo bin/enable_shankyou.sh        Idempotent.
set -euo pipefail

CONF=/etc/apache2/sites-enabled/default-ssl.conf

if grep -q 'go_shankyou' "$CONF"; then
  echo "Apache already has go_shankyou entries — skipping edit."
else
  cp "$CONF" "$CONF.bak.$(date +%s)"
  sed -i 's|\t\tProxyPass /api/ http://127.0.0.1:5001/api/|\t\tProxyPass /go_shankyou/ http://127.0.0.1:5001/go_shankyou/\n\t\tProxyPassReverse /go_shankyou/ http://127.0.0.1:5001/go_shankyou/\n\t\tProxyPass /sharp/ http://127.0.0.1:5001/sharp/\n\t\tProxyPassReverse /sharp/ http://127.0.0.1:5001/sharp/\n\t\tProxyPass /api/ http://127.0.0.1:5001/api/|' "$CONF"
  echo "Apache conf updated (backup kept)."
fi

apache2ctl configtest
apache2ctl graceful
supervisorctl restart watcher_signup
sleep 2
supervisorctl status watcher_signup

echo
echo "Smoke test:"
TOKEN=$(cd /home/shg/drop-watcher && python3 -c "import sharp; print(sharp.make_token('smoke-test','https://example.com/knife','smoke'))")
curl -s -o /dev/null -w 'local  %{http_code} -> %{redirect_url}\n' "http://127.0.0.1:5001/go_shankyou/$TOKEN"
curl -s -o /dev/null -w 'public %{http_code} -> %{redirect_url}\n' "https://instockornot.club/go_shankyou/$TOKEN"
echo "Done. Click rows: sqlite3 /var/lib/drop-watcher/dropwatcher.db 'SELECT * FROM outbound_clicks;'"
