# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""match_and_alert.py — match a single drop against all active watchers.

Called by web_watcher/feed_watcher immediately after writing a drop,
AND by per_user_alerter as a sweep for anything that slipped through.
"""
import hashlib
import logging
import re
from datetime import datetime, timezone

import db
from per_user_alerter import (
    matches_for_watcher_drop, build_alert_email, cooldown_key,
    COOLDOWN_HOURS,
)
from alerter import send_email
from urls import domain_from_url

log = logging.getLogger(__name__)


def match_drop(drop):
    """Match one drop against all active watchers. Send alerts. Returns count sent."""
    active = db.get_active_watchers()
    if not active:
        return 0

    now = datetime.now(timezone.utc)
    sent = 0

    email_alerts = {}
    for watcher in active:
        matches = matches_for_watcher_drop(watcher, drop)
        if not matches:
            continue

        drop_url = (drop.get('url') or '').lower()
        ck = cooldown_key(watcher['id'], drop_url, matches)
        if db.is_cooldown_active(ck, hours=COOLDOWN_HOURS):
            continue

        email = watcher['email']
        if email not in email_alerts:
            email_alerts[email] = []
        email_alerts[email].append((watcher, matches, ck))

    for email, alerts in email_alerts.items():
        for watcher, matches, ck in alerts:
            try:
                subject, html, txt = build_alert_email(watcher, matches, drop)
                result = send_email(subject, html, txt, to_addr=email)
            except Exception as e:
                log.error(f"match_drop alert failed for {email}: {e}")
                continue

            if result:
                db.mark_cooldown(ck, recipient=email)
                db.update_watcher(watcher['id'],
                    last_alert=now.isoformat(),
                    alert_count=watcher.get('alert_count', 0) + 1)
                log.info(f"[event] Alert sent to {email} for {drop.get('source', '')}")
                sent += 1

                if (watcher.get('sms_approved')
                        and (watcher.get('phone') or '').strip()
                        and drop.get('priority') in ('high', 'critical')):
                    try:
                        from sms_alerter import format_sms, _send_twilio_sms
                        body = format_sms(
                            {'source': drop.get('source', '')},
                            email=email,
                            keywords=','.join(matches),
                            token=watcher.get('unsubscribe_token'),
                        )
                        phone = watcher['phone'].strip()
                        if not phone.startswith('+'):
                            phone = '+1' + re.sub(r'\D', '', phone)
                        _send_twilio_sms(phone, body)
                    except Exception as e:
                        log.error(f"SMS fan-out exception for {email}: {e}")

    return sent
