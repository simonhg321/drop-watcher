# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
morning_matches.py — Simon's 7am eyeball digest.

Every matched drop alerted to users in the last 24h, deduped across
recipients (one entry per drop, matched keywords merged), with the deep
links — for review and possible buying. Source of truth is
emails_sent.log, so this shows exactly what users were sent.

Run via cron at 14:00 UTC (7am Pacific). --dry prints instead of sending.
HGR
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paths
from alerter import send_email

DIGEST_TO = 'info@instockornot.club'
LOOKBACK_HOURS = 24

HEAD_RE = re.compile(r'(\S+) \| TO: (\S+) \| SUBJ: (.*?) \| TYPE: (\S+)')
ITEM_RE = re.compile(r'^\s+- (.+?)$\n\s+(https?://\S+)', re.M)


def load_recent_match_alerts():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    out = []
    with open(paths.EMAILS_SENT_LOG) as f:
        for rec in f.read().split('\n===\n'):
            head, _, body = rec.partition('\n---\n')
            m = HEAD_RE.match(head.strip())
            if not m:
                continue
            ts, to, subj, typ = m.groups()
            if typ != 'alert' or 'Match found' not in subj:
                continue
            when = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if when < cutoff:
                continue
            kw = re.search(r'^Matched: (.+)$', body, re.M)
            page = re.search(r'^Page: (.+)$', body, re.M)
            src = re.search(r'^Source: (.+)$', body, re.M)
            items = ITEM_RE.findall(body)
            out.append({
                'ts': ts, 'to': to,
                'source': src.group(1).strip() if src else '?',
                'page': page.group(1).strip() if page else '',
                'keywords': kw.group(1).strip() if kw else '',
                'items': items,
                'low_conf': '🤔' in body,
            })
    return out


def dedupe(alerts):
    """One entry per drop: key on source + items; merge keywords/recipients."""
    drops = {}
    for a in alerts:
        key = (a['source'], tuple(u for _, u in a['items']) or a['page'])
        d = drops.setdefault(key, {**a, 'keywords': set(), 'recipients': set()})
        d['keywords'].update(k.strip() for k in a['keywords'].split(',') if k.strip())
        d['recipients'].add(a['to'])
        d['ts'] = min(d['ts'], a['ts'])
    return sorted(drops.values(), key=lambda d: d['ts'], reverse=True)


def render(drops):
    lines = [f"MATCHED DROPS — last {LOOKBACK_HOURS}h — {len(drops)} unique drops\n"]
    for d in drops:
        flag = ' [low-conf]' if d['low_conf'] else ''
        lines.append(f"{d['ts'][5:16]}  {d['source']}{flag}")
        lines.append(f"  KW: {', '.join(sorted(d['keywords']))}   "
                     f"(alerted {len(d['recipients'])} user{'s' if len(d['recipients']) != 1 else ''})")
        if d['items']:
            for title, url in d['items']:
                title = re.sub(r' 🤔.*$', '', title)
                lines.append(f"    - {title}")
                lines.append(f"      {url}")
        else:
            lines.append(f"    (no items extracted) {d['page']}")
        lines.append('')
    lines.append('HGR · bin/morning_matches.py')
    return '\n'.join(lines)


def main():
    drops = dedupe(load_recent_match_alerts())
    if not drops:
        body = "No matched drops in the last 24h.\n\nHGR · bin/morning_matches.py"
    else:
        body = render(drops)
    if '--dry' in sys.argv:
        print(body)
        return
    import html
    subject = f"[DROP WATCHER] Morning matches — {len(drops)} drops, last 24h"
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
