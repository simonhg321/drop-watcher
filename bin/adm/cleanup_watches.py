#!/usr/bin/env python3
"""Clean up watcher URLs — strip tracking params, flag homepages.
Usage:
  python3 bin/cleanup_watches.py          # dry run
  python3 bin/cleanup_watches.py --apply  # write changes
"""
import json, sys, os
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

WATCHERS = '/var/lib/drop-watcher/watchers.json'

# Tracking/ad params to strip
JUNK_PARAMS = {
    'gclid', 'gclsrc', 'gbraid', 'gad_source', 'gad_campaignid',
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
    'srsltid', 'TCID', 'wmlspartner', 'veh', 'cn', 'wl9', 'wl11',
    'sourceid', 'dclid', 'fbclid', 'msclkid', 'mc_cid', 'mc_eid',
}

def clean_url(url):
    """Strip tracking params from URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k.lower() not in JUNK_PARAMS}
    new_query = urlencode(cleaned, doseq=True) if cleaned else ''
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, ''  # drop fragment too
    ))

def is_homepage(url):
    """Check if URL is just a domain root."""
    parsed = urlparse(url)
    return parsed.path in ('', '/')

apply = '--apply' in sys.argv

with open(WATCHERS, 'r') as f:
    watchers = json.load(f)

changes = []
homepages = []

for w in watchers:
    url = w.get('url', '')
    if not url:
        continue

    new_url = clean_url(url)
    if new_url != url:
        changes.append({
            'email': w.get('email', ''),
            'old': url,
            'new': new_url,
            'keywords': w.get('keywords', ''),
        })
        if apply:
            w['url'] = new_url

    check_url = new_url if new_url != url else url
    if is_homepage(check_url) and w.get('active'):
        homepages.append({
            'email': w.get('email', ''),
            'url': check_url,
            'keywords': w.get('keywords', ''),
        })

# Report
if changes:
    print(f"URL CLEANUP — {len(changes)} URLs to fix:\n")
    for c in changes:
        print(f"  {c['email']}")
        print(f"    OLD: {c['old']}")
        print(f"    NEW: {c['new']}")
        print()
else:
    print("No tracking params found.\n")

if homepages:
    print(f"HOMEPAGE WATCHES — {len(homepages)} active watches on root URLs:\n")
    for h in homepages:
        print(f"  {h['email']}")
        print(f"    URL: {h['url']}")
        print(f"    KW:  {h['keywords']}")
        print()

if apply and changes:
    backup = WATCHERS + '.bak'
    with open(backup, 'w') as f:
        json.dump(watchers, f, indent=2)
    with open(WATCHERS, 'w') as f:
        json.dump(watchers, f, indent=2)
    print(f"Applied {len(changes)} changes. Backup at {backup}")
elif changes:
    print("DRY RUN — run with --apply to write changes.")
