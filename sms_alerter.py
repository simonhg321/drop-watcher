# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
sms_alerter.py
Drop Watcher — Twilio SMS Alert System
Sends SMS for CRITICAL alerts to sms_approved watchers.
Called by alerter.py — never blocks email path.
HGR
"""

import os
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# ── Load environment ──────────────────────────────────────────────────────────
import paths
load_dotenv(paths.ENV_FILE, override=True)

# ── Config ────────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID    = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN     = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_FROM           = os.environ.get('TWILIO_FROM')  # +19282498690
TWILIO_MESSAGING_SID  = os.environ.get('TWILIO_MESSAGING_SID')  # MG... — A2P campaign

WATCHERS_FILE = paths.WATCHERS_JSON
SMS_SENT_LOG  = paths.SMS_SENT_JSONL

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger('sms_alerter')

# ── Format SMS message ────────────────────────────────────────────────────────
def format_sms(alert):
    return "Drop Watcher: New drop alert — check your email for details. Reply STOP to opt out."

    return msg

# ── Check if SMS already sent for this alert+phone ───────────────────────────
def already_sent_sms(alert_id, phone):
    if not os.path.exists(SMS_SENT_LOG):
        return False
    with open(SMS_SENT_LOG, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get('alert_id') == alert_id and entry.get('phone') == phone:
                    return True
            except:
                continue
    return False

def mark_sms_sent(alert_id, phone):
    os.makedirs(os.path.dirname(SMS_SENT_LOG), exist_ok=True)
    with open(SMS_SENT_LOG, 'a') as f:
        f.write(json.dumps({
            'alert_id': alert_id,
            'phone': phone,
            'sent_at': datetime.now(timezone.utc).isoformat()
        }) + '\n')

# ── Get approved SMS recipients from watchers.json ───────────────────────────
def get_approved_phones():
    if not os.path.exists(WATCHERS_FILE):
        return []
    try:
        with open(WATCHERS_FILE, 'r') as f:
            watchers = json.load(f)
        phones = []
        for w in watchers:
            if w.get('sms_approved') and w.get('phone'):
                phones.append(w['phone'].strip())
        return phones
    except Exception as e:
        log.error(f"Failed to load watchers.json: {e}")
        return []

# ── Send a single SMS via Twilio ──────────────────────────────────────────────
def _send_twilio_sms(to_phone, body):
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
        log.error("Twilio credentials not configured in .env")
        return False
    if not TWILIO_MESSAGING_SID and not TWILIO_FROM:
        log.error("Need TWILIO_MESSAGING_SID or TWILIO_FROM in .env")
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        params = {'body': body, 'to': to_phone}
        if TWILIO_MESSAGING_SID:
            params['messaging_service_sid'] = TWILIO_MESSAGING_SID
        else:
            params['from_'] = TWILIO_FROM
        message = client.messages.create(**params)
        log.info(f"SMS sent to {to_phone} — sid: {message.sid}")
        return True
    except Exception as e:
        log.error(f"Twilio SMS failed to {to_phone}: {e}")
        return False

# ── Main entry point — called by alerter.py ───────────────────────────────────
def send_sms_alert(alert):
    """
    Send SMS for a CRITICAL alert to all sms_approved watchers.
    Silently fails — never raises, never blocks email path.
    """
    try:
        priority = alert.get('priority', '').lower()
        if priority != 'critical':
            return  # SMS is CRITICAL only

        alert_id = f"{alert.get('timestamp','')}_{alert.get('source','')}"
        phones   = get_approved_phones()

        if not phones:
            log.info("No sms_approved watchers — skipping SMS")
            return

        body = format_sms(alert)
        sent = 0

        for phone in phones:
            if already_sent_sms(alert_id, phone):
                continue
            if _send_twilio_sms(phone, body):
                mark_sms_sent(alert_id, phone)
                sent += 1

        if sent:
            log.info(f"SMS sent to {sent} watcher(s) for: {alert.get('source')}")

    except Exception as e:
        log.error(f"send_sms_alert failed: {e}")
        # Never re-raise — email path must not be affected

# ── Test / standalone ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        test_phone = sys.argv[2] if len(sys.argv) > 2 else None
        if not test_phone:
            print("Usage: python3 sms_alerter.py test +1xxxxxxxxxx")
            sys.exit(1)

        log.info(f"Sending test SMS to {test_phone}...")
        test_alert = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'priority': 'critical',
            'source': 'Test — Drop Watcher',
            'url': 'https://instockornot.club',
            'notable_items': ['Hinderer x Steel Flame XM-18 — 1 in stock'],
        }
        body = format_sms(test_alert)
        print(f"Message ({len(body)} chars): {body}")
        success = _send_twilio_sms(test_phone, body)
        print("✓ SMS sent!" if success else "✗ SMS failed — check logs")
    else:
        print("Usage: python3 sms_alerter.py test +1xxxxxxxxxx")
