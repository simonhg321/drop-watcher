#!/usr/bin/env python3
"""
trim_drops.py — Retain last 30 days of drops.jsonl, discard older.
Run daily via cron: 0 4 * * * python3 /home/shg/drop-watcher/bin/trim_drops.py
HGR
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

RETAIN_DAYS = 30
DROPS_FILE = paths.DROPS_JSONL


def trim():
    if not os.path.exists(DROPS_FILE):
        print("No drops file found.")
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)).isoformat()
    kept = []
    total = 0

    with open(DROPS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                d = json.loads(line)
                if (d.get('timestamp') or '') >= cutoff:
                    kept.append(line)
            except Exception:
                continue

    trimmed = total - len(kept)
    if trimmed == 0:
        print(f"Nothing to trim. {total} drops all within {RETAIN_DAYS} days.")
        return

    tmp = DROPS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        for line in kept:
            f.write(line + '\n')
    os.replace(tmp, DROPS_FILE)

    print(f"Trimmed {trimmed} drops older than {RETAIN_DAYS} days. Kept {len(kept)}.")


if __name__ == '__main__':
    trim()
