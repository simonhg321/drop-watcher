#!/usr/bin/env python3
"""
normalize_tokens.py — One-time fix: give all watches for the same email
the same unsubscribe_token. Run once after deploying shared-token signup.
HGR
"""

import json
import os
import sys

DATA_DIR = os.environ.get('DW_DATA_DIR', '/var/lib/drop-watcher')
WATCHERS_FILE = os.path.join(DATA_DIR, 'watchers.json')

with open(WATCHERS_FILE) as f:
    watchers = json.load(f)

# Group by email, pick first token as the canonical one
email_tokens = {}
fixed = 0
for w in watchers:
    email = w.get('email', '').lower()
    if not email:
        continue
    if email not in email_tokens:
        email_tokens[email] = w['unsubscribe_token']
    elif w['unsubscribe_token'] != email_tokens[email]:
        w['unsubscribe_token'] = email_tokens[email]
        fixed += 1

if fixed == 0:
    print("All tokens already normalized. Nothing to do.")
    sys.exit(0)

# Write back
tmp = WATCHERS_FILE + '.tmp'
with open(tmp, 'w') as f:
    json.dump(watchers, f, indent=2)
os.replace(tmp, WATCHERS_FILE)

print(f"Normalized {fixed} watches across {len(email_tokens)} emails.")
for email, token in email_tokens.items():
    count = sum(1 for w in watchers if w.get('email', '').lower() == email)
    print(f"  {email}: {count} watches → token {token[:8]}...")
