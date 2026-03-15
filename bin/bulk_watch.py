#!/usr/bin/env python3
"""Bulk-create watchers from sources.yaml for a given email + keywords."""
import json
import uuid
import yaml
from datetime import datetime, timezone

EMAIL = "simonhg@gmail.com"
NAME = "Simon"
KEYWORDS = "Damascus, skeleton, chris reeve"

SOURCES = "/etc/drop-watcher/sources.yaml"
WATCHERS = "/var/lib/drop-watcher/watchers.json"

# Load existing watchers
try:
    with open(WATCHERS) as f:
        watchers = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    watchers = []

# Load sources
with open(SOURCES) as f:
    sources = yaml.safe_load(f)

existing_urls = {w['url'].rstrip('/').lower() for w in watchers if w.get('email', '').lower() == EMAIL.lower()}

added = 0
for site in sources.get('websites', []):
    if not site.get('enabled', False):
        continue
    url = site['url'].rstrip('/')
    if url.lower() in existing_urls:
        print(f"  SKIP {site['name']} — already watching")
        continue
    entry = {
        'id': uuid.uuid4().hex[:8],
        'verify_token': None,
        'unsubscribe_token': str(uuid.uuid4()),
        'url': url,
        'keywords': KEYWORDS,
        'email': EMAIL,
        'name': NAME,
        'priority': 'high',
        'phone': '',
        'sms_approved': False,
        'active': True,
        'created': datetime.now(timezone.utc).isoformat(),
        'last_alert': None,
        'alert_count': 0,
    }
    watchers.append(entry)
    print(f"  ADDED {site['name']} — {url}")
    added += 1

with open(WATCHERS, 'w') as f:
    json.dump(watchers, f, indent=2)

print(f"\nDone: {added} watches added, {len(watchers)} total")
