#!/usr/bin/env python3
"""
token_report.py — Show Anthropic API token usage from api_usage.jsonl
Run: python3 bin/token_report.py          (today)
     python3 bin/token_report.py 7        (last 7 days)
     python3 bin/token_report.py all      (everything)
HGR
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

# Haiku pricing per 1M tokens (as of 2025)
INPUT_COST_PER_M  = 0.80   # $/1M input tokens
OUTPUT_COST_PER_M = 4.00   # $/1M output tokens

def load_usage(days=None):
    if not os.path.exists(paths.API_USAGE_JSONL):
        return []

    cutoff = None
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    entries = []
    with open(paths.API_USAGE_JSONL) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if cutoff and (e.get('ts', '') < cutoff):
                    continue
                entries.append(e)
            except Exception:
                continue
    return entries


def report(entries):
    if not entries:
        print("No API usage recorded yet.")
        return

    total_in = 0
    total_out = 0
    by_caller = defaultdict(lambda: {'calls': 0, 'in': 0, 'out': 0})
    by_day = defaultdict(lambda: {'calls': 0, 'in': 0, 'out': 0})

    for e in entries:
        inp = e.get('input_tokens', 0)
        out = e.get('output_tokens', 0)
        total_in += inp
        total_out += out

        caller = e.get('caller', 'unknown')
        by_caller[caller]['calls'] += 1
        by_caller[caller]['in'] += inp
        by_caller[caller]['out'] += out

        day = e.get('ts', '')[:10]
        by_day[day]['calls'] += 1
        by_day[day]['in'] += inp
        by_day[day]['out'] += out

    total_cost = (total_in / 1_000_000 * INPUT_COST_PER_M) + (total_out / 1_000_000 * OUTPUT_COST_PER_M)

    print(f"\n{'='*50}")
    print(f"  API TOKEN USAGE — {len(entries)} calls")
    print(f"{'='*50}")
    print(f"  Input tokens:   {total_in:>10,}")
    print(f"  Output tokens:  {total_out:>10,}")
    print(f"  Est. cost:      ${total_cost:>9.4f}")
    print()

    print(f"  {'CALLER':<20} {'CALLS':>6} {'IN':>10} {'OUT':>10} {'COST':>9}")
    print(f"  {'-'*20} {'-'*6} {'-'*10} {'-'*10} {'-'*9}")
    for caller, d in sorted(by_caller.items()):
        cost = (d['in'] / 1_000_000 * INPUT_COST_PER_M) + (d['out'] / 1_000_000 * OUTPUT_COST_PER_M)
        print(f"  {caller:<20} {d['calls']:>6} {d['in']:>10,} {d['out']:>10,} ${cost:>8.4f}")
    print()

    print(f"  {'DAY':<12} {'CALLS':>6} {'IN':>10} {'OUT':>10} {'COST':>9}")
    print(f"  {'-'*12} {'-'*6} {'-'*10} {'-'*10} {'-'*9}")
    for day in sorted(by_day.keys()):
        d = by_day[day]
        cost = (d['in'] / 1_000_000 * INPUT_COST_PER_M) + (d['out'] / 1_000_000 * OUTPUT_COST_PER_M)
        print(f"  {day:<12} {d['calls']:>6} {d['in']:>10,} {d['out']:>10,} ${cost:>8.4f}")

    print(f"{'='*50}\n")


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else '1'
    if arg == 'all':
        entries = load_usage(days=None)
    else:
        try:
            days = int(arg)
        except ValueError:
            days = 1
        entries = load_usage(days=days)
    report(entries)
