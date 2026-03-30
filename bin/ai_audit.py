#!/usr/bin/env python3
"""
ai_audit.py — dump recent AI calls for human review
Shows what we sent to Haiku and what came back.

Usage:
  python3 bin/ai_audit.py          # last 5 calls
  python3 bin/ai_audit.py 10       # last 10
  python3 bin/ai_audit.py user     # only user watch calls
  python3 bin/ai_audit.py curated  # only curated calls

HGR
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import paths

count = 5
filter_type = None

for arg in sys.argv[1:]:
    if arg in ('user', 'curated'):
        filter_type = arg.upper()
    elif arg.isdigit():
        count = int(arg)

ai_path = paths.AI_CALLS_JSONL
if not os.path.exists(ai_path):
    print(f"No AI calls log at {ai_path}")
    sys.exit(1)

entries = []
with open(ai_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if filter_type and filter_type.lower() not in entry.get('caller', '').lower():
                continue
            entries.append(entry)
        except json.JSONDecodeError:
            continue

for entry in entries[-count:]:
    ts = entry.get('ts', '?')[:19]
    caller = entry.get('caller', '?')
    site = entry.get('site', '?')
    url = entry.get('url', '')
    print(f"\n{'=' * 80}")
    print(f"TIME: {ts}  CALLER: {caller}  SITE: {site}")
    if url:
        print(f"URL: {url}")
    print(f"{'─' * 80}")

    prompt = entry.get('prompt_snippet', '')
    if prompt:
        print(f"PROMPT SNIPPET ({len(prompt)} chars):")
        print(prompt)
    else:
        print("PROMPT: (not logged)")

    print(f"{'─' * 80}")

    response = entry.get('response', '')
    if isinstance(response, dict):
        alert = response.get('alert_worthy', '')
        priority = response.get('priority', '')
        summary = response.get('page_summary', '')
        items = response.get('notable_items', [])
        makers = response.get('makers_found', response.get('keywords_found', []))
        print(f"ALERT: {alert}  PRI: {priority}  MAKERS/KW: {', '.join(makers) if makers else 'none'}")
        if items:
            print(f"ITEMS: {'; '.join(str(i) for i in items)}")
        print(f"SUMMARY: {summary}")
    elif isinstance(response, str):
        print(f"RESPONSE: {response}")
    else:
        print(f"RAW: {response}")

    print(f"{'=' * 80}")

print(f"\nShowing {min(count, len(entries))} of {len(entries)} calls" + (f" (filtered: {filter_type})" if filter_type else ""))
