#!/usr/bin/env python3
"""Find watchers by URL domain. Usage: python3 bin/find_watcher.py davidyurman"""
import json, sys

if len(sys.argv) < 2:
    print("Usage: python3 bin/find_watcher.py <domain-fragment>")
    sys.exit(1)

q = sys.argv[1].lower()
with open('/var/lib/drop-watcher/watchers.json') as f:
    watchers = json.load(f)

for w in watchers:
    if q in w.get('url', '').lower():
        print(json.dumps({
            'url': w.get('url'),
            'keywords': w.get('keywords'),
            'email': w.get('email'),
            'status': w.get('status'),
            'priority': w.get('priority'),
        }, indent=2))
        print()
