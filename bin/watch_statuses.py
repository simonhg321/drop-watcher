#!/usr/bin/env python3
"""Show all watcher statuses and counts.
Usage: python3 bin/watch_statuses.py
"""
import json
from collections import Counter

with open('/var/lib/drop-watcher/watchers.json') as f:
    watchers = json.load(f)

counts = Counter(w.get('status', 'MISSING') for w in watchers)
print(f"Total watches: {len(watchers)}\n")
for status, count in counts.most_common():
    print(f"  {status}: {count}")

print("\nSample entry keys:", list(watchers[0].keys()) if watchers else "empty")
