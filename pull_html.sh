#!/bin/bash
# pull_html.sh — Pull live HTML from ironman webroot to local html/
# Run from drop-watcher directory on Mac
# HGR

scp shg@instockornot.club:/var/www/html/index.html \
    shg@instockornot.club:/var/www/html/watchlist.html \
    shg@instockornot.club:/var/www/html/my-alerts.html \
    shg@instockornot.club:/var/www/html/get-my-link.html \
    shg@instockornot.club:/var/www/html/privacy.html \
    shg@instockornot.club:/var/www/html/hgr.html \
    shg@instockornot.club:/var/www/html/watcher_status.html \
    html/

echo "Done. Run 'git diff html/' to see what changed."
