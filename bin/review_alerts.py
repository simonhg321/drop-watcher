# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
review_alerts.py — replay real user alerts to info@ for eyeballing.

Re-renders the most recent real watcher x drop matches through the SAME
build_alert_email() path users get (HTML and all) and sends them to
info@instockornot.club, subject-tagged [REVIEW -> user]. No cooldowns
are touched, nothing goes to users.

Run: python3 bin/review_alerts.py        (5 most recent, distinct sources)
     python3 bin/review_alerts.py 10     (N instead)
HGR
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import per_user_alerter as pua
from alerter import send_email

REVIEW_TO = 'info@instockornot.club'


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    watchers = db.get_active_watchers()
    drops = db.get_recent_drops(minutes=24 * 60)   # eyeball pool: last 24h

    hits = []
    for drop in drops:
        for w in watchers:
            matches = pua.matches_for_watcher_drop(w, drop)
            if matches:
                hits.append((drop.get('timestamp', ''), w, matches, drop))

    # newest first, one per source so the sample is diverse
    hits.sort(key=lambda h: h[0], reverse=True)
    seen_src, picked = set(), []
    for ts, w, matches, drop in hits:
        src = drop.get('source', '')
        if src in seen_src:
            continue
        seen_src.add(src)
        picked.append((w, matches, drop))
        if len(picked) >= n:
            break

    if not picked:
        print("no current matches to replay")
        return

    print(f"replaying {len(picked)} alerts to {REVIEW_TO}:")
    for w, matches, drop in picked:
        subject, html, txt = pua.build_alert_email(w, matches, drop)
        subject = f"[REVIEW → {w['email']}] " + subject
        ok = send_email(subject, html, txt, to_addr=REVIEW_TO)
        print(f"  {'ok  ' if ok else 'FAIL'} {subject[:90]}")


if __name__ == '__main__':
    main()
