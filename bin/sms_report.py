#!/usr/bin/env python3
"""
sms_report.py — Twilio SMS delivery report
Shows what actually got delivered vs failed.

Usage:
  python3 bin/sms_report.py          # last 7 days
  python3 bin/sms_report.py 30       # last 30 days
  python3 bin/sms_report.py all      # everything

HGR
"""
import os, sys, json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv('/etc/drop-watcher/.env')
from twilio.rest import Client

client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])

days = 7
if len(sys.argv) > 1:
    if sys.argv[1] == 'all':
        days = 365
    else:
        days = int(sys.argv[1])

since = datetime.now(timezone.utc) - timedelta(days=days)

print(f"SMS Report — last {days} days")
print(f"{'─' * 50}")

messages = client.messages.list(date_sent_after=since)

if not messages:
    print("No messages found.")
    sys.exit(0)

# Aggregate
by_status = {}
by_day = {}
total = 0

for m in messages:
    total += 1
    s = m.status
    by_status[s] = by_status.get(s, 0) + 1
    day = m.date_sent.strftime('%Y-%m-%d') if m.date_sent else 'unknown'
    if day not in by_day:
        by_day[day] = {'delivered': 0, 'sent': 0, 'failed': 0, 'undelivered': 0, 'other': 0}
    if s in by_day[day]:
        by_day[day][s] += 1
    else:
        by_day[day]['other'] += 1

# Summary
print(f"\nTotal: {total}")
for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
    pct = n / total * 100
    print(f"  {s:15s} {n:4d}  ({pct:.0f}%)")

# By day
print(f"\nBy day:")
print(f"  {'DATE':12s} {'DLVR':>5s} {'SENT':>5s} {'FAIL':>5s} {'UNDL':>5s}")
for day in sorted(by_day.keys()):
    d = by_day[day]
    print(f"  {day:12s} {d['delivered']:5d} {d['sent']:5d} {d['failed']:5d} {d['undelivered']:5d}")

# Recent messages
print(f"\nLast 10 messages:")
for m in messages[:10]:
    ts = m.date_sent.strftime('%m/%d %H:%M') if m.date_sent else '??'
    print(f"  {ts}  →{m.to or '??'}  {m.status:12s}  {m.body[:50] if m.body else ''}")
