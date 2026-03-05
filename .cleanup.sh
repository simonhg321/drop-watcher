#!/bin/bash
> ~/drop-watcher/logs/drops.jsonl
> ~/drop-watcher/logs/seen_items.json
python3 ~/drop-watcher/generate_alerts.py
