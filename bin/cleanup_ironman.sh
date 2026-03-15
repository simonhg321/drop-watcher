#!/bin/bash
# cleanup_ironman.sh — Remove dead files from ~/drop-watcher on ironman
# Run once. Review before running.
# HGR

echo "=== Removing dead scripts ==="
rm -v ~/drop-watcher/fix_nav.py
rm -v ~/drop-watcher/watcher_output.py
rm -v ~/drop-watcher/nuke_watchers_tokens.py
rm -v ~/drop-watcher/restart_stuff.sh
rm -v ~/drop-watcher/test-xss-cmd.sh
rm -v ~/drop-watcher/test-escape.py
rm -v ~/drop-watcher/dw.sh
rm -v ~/drop-watcher/orchestrator.py

echo "=== Removing dead HTML ==="
rm -v ~/drop-watcher/watcher_status.html

echo "=== Removing old setup notes ==="
rm -v ~/drop-watcher/watchlist-setup.md

echo "=== Done ==="
echo "Left alone: instockornot_zone.txt (DNS ref), gunicorn.ctl (socket), logs/ data/ config/ (old dirs — empty later if confirmed)"
