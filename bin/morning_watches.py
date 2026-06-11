# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
morning_watches.py — Simon's 7am watch-health sample.

One email with a rotating 30% sample of ACTIVE watches (keywords + URL +
last-alert stats) so Simon can eyeball match quality. The sample window
strides by calendar day, so every watch appears roughly every 4 days.

Run via cron at 14:02 UTC (7am Pacific). --dry prints instead of sending.
HGR
"""
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from alerter import send_email

DIGEST_TO = 'info@instockornot.club'
SAMPLE_FRACTION = 0.30


def pick_sample(watchers):
    watchers = sorted(watchers, key=lambda w: w['id'])
    k = max(1, math.ceil(len(watchers) * SAMPLE_FRACTION))
    day = datetime.now(timezone.utc).toordinal()
    start = (day * k) % len(watchers)
    wrapped = watchers[start:] + watchers[:start]
    return wrapped[:k], k


def fmt_age(iso):
    if not iso:
        return 'never'
    try:
        then = datetime.fromisoformat(iso)
        days = (datetime.now(timezone.utc) - then).days
        return 'today' if days == 0 else f'{days}d ago'
    except ValueError:
        return iso[:10]


def render(sample, total):
    lines = [f"WATCH HEALTH — {len(sample)} of {total} active watches "
             f"(30% rotating sample, full coverage ~4 days)\n"]
    for w in sorted(sample, key=lambda w: (w['email'], w['keywords'])):
        target = w['url'] or f"(global maker watch: {w['maker'] or '?'})"
        lines.append(f"{w['email']}")
        lines.append(f"  KW:    {w['keywords']}")
        lines.append(f"  URL:   {target}")
        lines.append(f"  stats: {w['alert_count']} alerts ever, last {fmt_age(w['last_alert'])}, "
                     f"watching since {(w['created'] or '')[:10]}")
        lines.append('')
    lines.append('HGR · bin/morning_watches.py')
    return '\n'.join(lines)


def main():
    watchers = db.get_active_watchers()
    sample, k = pick_sample(watchers)
    body = render(sample, len(watchers))
    if '--dry' in sys.argv:
        print(body)
        return
    import html
    subject = f"[DROP WATCHER] Watch health — {len(sample)} of {len(watchers)} watches (30% sample)"
    ok = send_email(
        subject=subject,
        body_html=('<pre style="font-family:Consolas,Menlo,monospace;'
                   f'font-size:13px;">{html.escape(body)}</pre>'),
        body_text=body,
        to_addr=DIGEST_TO)
    print('sent' if ok else 'FAILED', subject)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
