#!/usr/bin/env python3
"""Show all active user watches — what we're scraping and sending to Haiku.
Usage: python3 bin/active_user_watches.py
"""
import json

with open('/var/lib/drop-watcher/watchers.json') as f:
    watchers = json.load(f)

active = [w for w in watchers if w.get('active')]
print(f"Active watches: {len(active)}\n")

by_url = {}
for w in active:
    url = w.get('url', '')
    if url not in by_url:
        by_url[url] = []
    by_url[url].append({
        'email': w.get('email', ''),
        'keywords': w.get('keywords', ''),
        'priority': w.get('priority', ''),
    })

for url, users in sorted(by_url.items()):
    print(f"URL: {url}")
    for u in users:
        print(f"  {u['email']} — kw: {u['keywords']} — pri: {u['priority']}")
    print()
