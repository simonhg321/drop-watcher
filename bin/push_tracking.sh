#!/bin/bash
# Push cookie tracking files to ironman
# SGH

set -e

HOST="shg@instockornot.club"

echo "Pushing tracking files to ironman..."

scp html/dw-track.js "$HOST:/var/www/html/dw-track.js"
scp watcher_signup.py "$HOST:~/drop-watcher/watcher_signup.py"
scp paths.py "$HOST:~/drop-watcher/paths.py"
scp html/index.html "$HOST:/var/www/html/index.html"
scp html/watchlist.html "$HOST:/var/www/html/watchlist.html"
scp html/my-alerts.html "$HOST:/var/www/html/my-alerts.html"
scp html/get-my-link.html "$HOST:/var/www/html/get-my-link.html"
scp html/what-we-watch.html "$HOST:/var/www/html/what-we-watch.html"
scp html/alerts.html "$HOST:/var/www/html/alerts.html"
scp html/privacy.html "$HOST:/var/www/html/privacy.html"
scp html/terms.html "$HOST:/var/www/html/terms.html"

echo "Done. Now run on ironman:"
echo "  sudo supervisorctl restart watcher_signup"
