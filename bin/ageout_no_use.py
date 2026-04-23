#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
ageout_no_use.py — Age out active watches whose owner has stopped engaging.

Flow:
  Stage A (nudge): a watch has fired an alert, 3+ days have passed, and the
                   user has not clicked the "keep this watch alive" link
                   since that alert → send a confirmation email, record
                   ageout_email_sent=now.
  Stage B (tear): the confirmation email went out 6+ hours ago and still
                  no ack → set active=0. Row is preserved.

Engagement is per-email: clicking "keep alive" on any alert refreshes
last_acked for every watch under that email.

Cron: 0 * * * * python3 /home/shg/drop-watcher/bin/ageout_no_use.py
HGR
"""

import html as html_mod
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paths  # noqa: F401
import db
import alerter as _alerter
from alerter import send_email

NUDGE_AFTER_DAYS = 3
TEARDOWN_AFTER_HOURS = 6

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ageout_no_use] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)


def build_nudge_email(watcher):
    name = html_mod.escape(watcher.get('name') or 'there')
    url = html_mod.escape(watcher.get('url', ''))
    kws = html_mod.escape(watcher.get('keywords', ''))
    unsub = watcher['unsubscribe_token']
    keep_url = f"https://instockornot.club/api/ack/{unsub}"
    unsub_url = f"https://instockornot.club/api/unsubscribe/{unsub}"

    subject = "[DROP WATCHER] Still want this watch?"
    html = f"""
    <div style="font-family: monospace; background: #0a0a0a; color: #e8e8e8; padding: 24px; max-width: 600px;">
      <h2 style="color: #ff2d2d; margin: 0 0 16px;">⚡ DROP WATCHER</h2>
      <p>Hey {name} — we've been sending you alerts but haven't heard back in a while.</p>
      <p>Do you still want alerts for:</p>
      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Page</div>
        <div style="color:#e8e8e8;font-size:12px;word-break:break-all">{url}</div>
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin: 12px 0 8px;">Keywords</div>
        <div style="color:#e8e8e8">{kws}</div>
      </div>
      <p style="margin: 20px 0 0;">
        <a href="{keep_url}" style="background: #27ae60; color: white; padding: 12px 24px; text-decoration: none; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;">Yes, keep it →</a>
      </p>
      <p style="color:#888;font-size:12px;margin-top:16px">
        If you don't click within {TEARDOWN_AFTER_HOURS} hours, we'll automatically stop your alerts.
      </p>
      <hr style="border: none; border-top: 1px solid #222; margin: 32px 0;">
      <p style="color: #444; font-size: 11px;">
        <a href="{unsub_url}" style="color: #444;">Unsubscribe now</a> · instockornot.club
      </p>
    </div>
    """
    text = (
        f"DROP WATCHER — Still want this watch?\n\n"
        f"We've been sending you alerts for:\n"
        f"  Page: {watcher.get('url','')}\n"
        f"  Keywords: {watcher.get('keywords','')}\n\n"
        f"Click to keep it active: {keep_url}\n\n"
        f"If you don't click within {TEARDOWN_AFTER_HOURS} hours, we'll stop your alerts.\n\n"
        f"Unsubscribe: {unsub_url}\n"
    )
    return subject, html, text


def nudge(now):
    """Stage A: find alerted-but-idle watches, send one nudge per email."""
    cutoff = (now - timedelta(days=NUDGE_AFTER_DAYS)).isoformat()
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM watchers
            WHERE active = 1
              AND last_alert IS NOT NULL
              AND last_alert < ?
              AND ageout_email_sent IS NULL
              AND (last_acked IS NULL OR last_acked < last_alert)
        """, (cutoff,)).fetchall()
        candidates = [dict(r) for r in rows]

    if not candidates:
        log.info("No nudge candidates.")
        return

    # Group idle watches by email; one nudge per email covers all their idle watches.
    by_email = {}
    for w in candidates:
        by_email.setdefault(w['email'].lower(), []).append(w)

    now_iso = now.isoformat()
    for email, idle_watches in by_email.items():
        representative = max(idle_watches, key=lambda x: x.get('last_alert') or '')
        subject, html, text = build_nudge_email(representative)
        original_to = _alerter.ALERT_TO
        _alerter.ALERT_TO = email
        try:
            ok = send_email(subject, html, text)
        finally:
            _alerter.ALERT_TO = original_to

        if ok:
            # Only flag the idle watches — engaged watches under the same email
            # stay untouched. One ack click clears all (ack endpoint is by email).
            for w in idle_watches:
                db.update_watcher(w['id'], ageout_email_sent=now_iso)
            log.info(f"Nudge sent to {email} covering {len(idle_watches)} idle watch(es)")
        else:
            log.error(f"Nudge send failed for {email}")


def teardown(now):
    """Stage B: confirmation email sent 6h+ ago and still no ack → deactivate."""
    cutoff = (now - timedelta(hours=TEARDOWN_AFTER_HOURS)).isoformat()
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT id, email, url, keywords FROM watchers
            WHERE active = 1
              AND ageout_email_sent IS NOT NULL
              AND ageout_email_sent < ?
              AND (last_acked IS NULL OR last_acked < ageout_email_sent)
        """, (cutoff,)).fetchall()
        stale = [dict(r) for r in rows]

    if not stale:
        log.info("No teardown candidates.")
        return

    for w in stale:
        db.update_watcher(w['id'], active=False)
        log.info(f"Aged out: {w['email']} | {w['url'][:60]} | kws={w['keywords'][:40]}")
    log.info(f"Deactivated {len(stale)} watch(es).")


def run():
    now = datetime.now(timezone.utc)
    nudge(now)
    teardown(now)
    log.info("Done.")


if __name__ == '__main__':
    run()
