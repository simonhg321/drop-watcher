#!/usr/bin/env bash
# fix_html_cache.sh — make browsers revalidate HTML instead of heuristically
# caching it. BUG-011: iPad Safari showed a stale watchlist.html (no ALL OUR
# SHOPS) because we send Last-Modified but no Cache-Control, so Safari reused
# the old copy without asking. no-cache forces a conditional request; unchanged
# pages still get a cheap 304, so no real bandwidth cost. Needs sudo.
# Run:  sudo bash ~/drop-watcher/bin/fix_html_cache.sh
# HGR
set -euo pipefail

CONF=/etc/apache2/conf-available/html-nocache.conf

cat > "$CONF" <<'EOF'
# HTML must revalidate on every load — without this, browsers (iPad Safari
# especially) heuristically cache .html and serve stale pages (BUG-011, S59).
# Static assets (css/js/img) are untouched and may cache normally.
<FilesMatch "\.html$">
  Header set Cache-Control "no-cache, must-revalidate"
</FilesMatch>
EOF

a2enconf html-nocache
apache2ctl configtest
systemctl reload apache2
sleep 2

echo "=== verify live header ==="
curl -sI --max-time 10 https://instockornot.club/watchlist.html | grep -i "cache-control" \
  && echo "VERIFIED ✓ — HTML now revalidates" \
  || { echo "✗ Cache-Control header not visible — check Cloudflare/conf"; exit 1; }
