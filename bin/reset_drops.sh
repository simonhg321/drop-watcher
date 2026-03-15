#!/bin/bash
# reset_drops.sh — Clear old drops and rebuild alerts page fresh
# Use after priority rule changes or to clean stale data
> /var/log/drop-watcher/drops.jsonl
python3 /home/shg/drop-watcher/generate_alerts.py >> /var/log/drop-watcher/generate_alerts.log 2>&1
echo "Drops cleared, alerts.html rebuilt. New scans will repopulate."
