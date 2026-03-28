# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
ai_calls.py — View what's going between Haiku and the pages we scrape.
Shows the page content snippet sent to AI and the full JSON response.

Usage:
  python3 bin/ai_calls.py            # last 10 calls
  python3 bin/ai_calls.py 20         # last 20 calls
  python3 bin/ai_calls.py user       # only user watch calls
  python3 bin/ai_calls.py curated    # only curated (sources.yaml) calls
  python3 bin/ai_calls.py all        # everything

HGR
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

def load_calls(filter_type=None, limit=10):
    calls = []
    try:
        with open(paths.AI_CALLS_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if filter_type == 'user' and entry.get('caller') != 'analyze_user_page':
                    continue
                if filter_type == 'curated' and entry.get('caller') != 'analyze_page':
                    continue
                calls.append(entry)
    except FileNotFoundError:
        print(f"No AI calls log yet at {paths.AI_CALLS_JSONL}")
        return []

    if limit > 0:
        calls = calls[-limit:]
    return calls


def print_call(entry):
    ts = entry.get('ts', '?')[:19].replace('T', ' ')
    caller = entry.get('caller', '?')
    site = entry.get('site', '?')
    url = entry.get('url', '?')
    snippet = entry.get('prompt_snippet', '')
    resp = entry.get('response', {})

    tag = 'USER' if caller == 'analyze_user_page' else 'CURATED'
    alert = resp.get('alert_worthy', False)
    priority = resp.get('priority', '?')

    print(f"\n{'='*80}")
    print(f"  [{tag}]  {ts}  {site}")
    print(f"  URL: {url}")
    print(f"  Alert worthy: {alert}  |  Priority: {priority}")
    print(f"{'─'*80}")

    # What we sent
    print(f"  SENT TO HAIKU (first 500 chars):")
    for line in snippet[:500].split('\n'):
        print(f"    {line}")

    # What came back
    print(f"{'─'*80}")
    print(f"  HAIKU RESPONSE:")

    if resp.get('keywords_found'):
        print(f"    Keywords found: {', '.join(resp['keywords_found'])}")
    if resp.get('makers_found'):
        print(f"    Makers found: {', '.join(resp['makers_found'])}")
    if resp.get('notable_items'):
        print(f"    Notable items:")
        for item in resp['notable_items']:
            print(f"      → {item}")
    if resp.get('page_summary'):
        print(f"    Summary: {resp['page_summary']}")
    if resp.get('stock_status'):
        print(f"    Stock status: {json.dumps(resp['stock_status'])}")
    if resp.get('drop_announcement', {}).get('detected'):
        da = resp['drop_announcement']
        print(f"    DROP: {da.get('maker')} — {da.get('description')} — {da.get('timing')}")

    print(f"{'='*80}")


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else '10'

    filter_type = None
    limit = 10

    if arg == 'user':
        filter_type = 'user'
    elif arg == 'curated':
        filter_type = 'curated'
    elif arg == 'all':
        limit = 0
    else:
        try:
            limit = int(arg)
        except ValueError:
            print(f"Usage: python3 bin/ai_calls.py [count|user|curated|all]")
            sys.exit(1)

    calls = load_calls(filter_type=filter_type, limit=limit)
    if not calls:
        print("No AI calls found.")
        sys.exit(0)

    print(f"\n  Showing {len(calls)} AI call(s)" + (f" [{filter_type}]" if filter_type else ""))

    for entry in calls:
        print_call(entry)

    print()
