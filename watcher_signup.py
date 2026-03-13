# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
watcher_signup.py — Flask API for public watch signups
Receives POST /api/watch, writes to watchers.json
Sends confirmation email via Resend on signup
Handles token-based unsubscribe via GET /api/unsubscribe/<token>

Run: gunicorn -w 2 -b 127.0.0.1:5001 watcher_signup:app
Apache proxies /api/ → localhost:5001
HGR
"""

import json
import os
import uuid
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHERS_FILE = os.path.join(BASE_DIR, 'config', 'watchers.json')

load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

RESEND_API_KEY   = os.environ.get('RESEND_API_KEY')
FROM_ADDRESS     = 'Drop Watcher <noreply@instockornot.club>'
RESEND_API_URL   = 'https://api.resend.com/emails'
BASE_URL         = 'https://instockornot.club'

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ── Watchers file helpers ─────────────────────────────────────────────────────

def load_watchers():
    if not os.path.exists(WATCHERS_FILE):
        return []
    with open(WATCHERS_FILE) as f:
        return json.load(f)


def save_watchers(watchers):
    os.makedirs(os.path.dirname(WATCHERS_FILE), exist_ok=True)
    with open(WATCHERS_FILE, 'w') as f:
        json.dump(watchers, f, indent=2)


# ── Confirmation email ────────────────────────────────────────────────────────

def send_confirmation_email(entry):
    if not RESEND_API_KEY:
        log.error("RESEND_API_KEY not set — cannot send confirmation email")
        return False

    name            = entry.get('name') or 'Collector'
    url             = entry['url']
    keywords        = entry['keywords']
    unsubscribe_url = f"{BASE_URL}/api/unsubscribe/{entry['unsubscribe_token']}"

    subject = "Drop Watcher — You're set up"

    body_text = f"""Hey {name},

You're now watching:
  URL: {url}
  Keywords: {keywords}

You'll get alerted when we detect a match. CRITICAL alerts go immediately, HIGH within 30 minutes.

To stop watching: {unsubscribe_url}

HGR
instockornot.club
"""

    body_html = f"""
    <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:24px;max-width:600px">
        <h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>
        <div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>

        <p style="color:#d0d0d0;font-size:16px">Hey {name}, you're set up.</p>

        <div style="background:#1c1c1c;padding:16px;margin:20px 0">
            <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:12px">WATCHING</div>
            <div style="margin-bottom:8px">
                <span style="color:#888;font-size:11px">URL</span><br>
                <a href="{url}" style="color:#e67e22;font-size:13px">{url}</a>
            </div>
            <div style="margin-top:12px">
                <span style="color:#888;font-size:11px">KEYWORDS</span><br>
                <span style="color:#f0f0f0;font-size:14px">{keywords}</span>
            </div>
        </div>

        <p style="color:#888;font-size:12px">CRITICAL alerts fire immediately. HIGH alerts within 30 minutes.</p>

        <div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#888;font-size:11px;letter-spacing:2px">
            <a href="https://instockornot.club/alerts.html" style="color:#e67e22">VIEW LIVE ALERTS</a>
            <div style="margin-top:8px;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>
            <p style="margin-top:12px">
                <a href="{unsubscribe_url}" style="color:#e67e22;font-size:12px">Unsubscribe</a>
            </p>
        </div>
    </body></html>"""

    payload = {
        'from':    FROM_ADDRESS,
        'to':      [entry['email']],
        'subject': subject,
        'html':    body_html,
        'text':    body_text,
        'headers': {
            'List-Unsubscribe':      f'<{unsubscribe_url}>',
            'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
        }
    }

    try:
        r = httpx.post(
            RESEND_API_URL,
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type':  'application/json',
            },
            json=payload,
            timeout=15
        )
        r.raise_for_status()
        log.info(f"Confirmation email sent to {entry['email']} — id: {r.json().get('id')}")
        return True
    except Exception as e:
        log.error(f"Confirmation email failed for {entry['email']}: {e}")
        return False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/api/watch', methods=['POST'])
def watch():
    data = request.get_json(force=True)

    # Validate required fields
    for field in ['url', 'keywords', 'email']:
        if not data.get(field, '').strip():
            return jsonify({'error': f'Missing required field: {field}'}), 400

    entry = {
        'id':                str(uuid.uuid4())[:8],
        'unsubscribe_token': str(uuid.uuid4()),  # full UUID — unguessable
        'url':               data['url'].strip(),
        'keywords':          data['keywords'].strip(),
        'email':             data['email'].strip().lower(),
        'name':              data.get('name', '').strip(),
        'priority':          data.get('priority', 'high'),
        'phone':             data.get('phone', '').strip(),
        'sms_approved':      False,
        'active':            True,
        'created':           datetime.now(timezone.utc).isoformat(),
        'last_alert':        None,
        'alert_count':       0,
    }

    watchers = load_watchers()

    # Deduplicate: same email + url combo
    existing = [w for w in watchers if w['email'] == entry['email'] and w['url'] == entry['url']]
    if existing:
        log.info(f"Duplicate watcher for {entry['email']} / {entry['url']} — updating keywords")
        existing[0]['keywords'] = entry['keywords']
        existing[0]['priority'] = entry['priority']
        save_watchers(watchers)
        return jsonify({'status': 'updated', 'id': existing[0]['id']}), 200

    watchers.append(entry)
    save_watchers(watchers)
    log.info(f"New watcher: {entry['id']} | {entry['email']} | {entry['url']}")

    # Send confirmation email — non-blocking, failure doesn't break signup
    send_confirmation_email(entry)

    return jsonify({'status': 'created', 'id': entry['id']}), 201


@app.route('/api/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    watchers = load_watchers()
    for w in watchers:
        # Support both token and legacy id-based unsubscribe
        if w.get('unsubscribe_token') == token or w.get('id') == token:
            if not w.get('active'):
                return jsonify({'status': 'already_unsubscribed'}), 200
            w['active'] = False
            save_watchers(watchers)
            log.info(f"Unsubscribed: {w['email']}")
            # Return a friendly HTML page for one-click unsubscribe
            if request.method == 'GET':
                return """
                <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#c0392b">DROP WATCHER</h1>
                    <p style="font-size:18px;margin-top:24px">You've been unsubscribed.</p>
                    <p style="color:#888;font-size:13px">You won't receive any more alerts from us.</p>
                    <p style="margin-top:32px"><a href="https://instockornot.club" style="color:#e67e22">instockornot.club</a></p>
                </body></html>""", 200
            return jsonify({'status': 'unsubscribed'}), 200
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/watchers', methods=['GET'])
def list_watchers():
    """Admin endpoint — restrict to localhost in Apache"""
    watchers = load_watchers()
    active = [w for w in watchers if w.get('active')]
    return jsonify({'count': len(active), 'watchers': active}), 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)
