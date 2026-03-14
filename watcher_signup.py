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

import html as html_mod
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
FROM_ADDRESS     = 'Drop Watcher <info@instockornot.club>'
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

    # Escape user input for HTML context
    safe_name     = html_mod.escape(name)
    safe_url      = html_mod.escape(url)
    safe_keywords = html_mod.escape(keywords)

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

        <p style="color:#d0d0d0;font-size:16px">Hey {safe_name}, you're set up.</p>

        <div style="background:#1c1c1c;padding:16px;margin:20px 0">
            <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:12px">MY ALERTS</div>
            <div style="margin-top:8px">
                <span style="color:#888;font-size:11px">KEYWORDS</span><br>
                <span style="color:#f0f0f0;font-size:14px">{safe_keywords}</span>
            </div>
        </div>
        <p style="color:#888;font-size:12px;margin-bottom:20px">Save this email — it contains your personal alerts link. If you lose it, visit <a href="{BASE_URL}/get-my-link.html" style="color:#e67e22">instockornot.club/get-my-link</a> and we will resend it.</p>

        <p style="color:#888;font-size:12px">CRITICAL alerts fire immediately. HIGH alerts within 30 minutes.</p>

        <div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#888;font-size:11px;letter-spacing:2px">
            <a href="{BASE_URL}/my-alerts.html?token={entry['unsubscribe_token']}" style="color:#e67e22;display:block;margin-bottom:8px">VIEW MY ALERTS</a>
            <a href="{BASE_URL}/alerts.html" style="color:#888;font-size:11px">View all alerts</a>
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



# ── Verification email (sent on signup) ──────────────────────────────────────────────────

def send_verification_email(entry):
    if not RESEND_API_KEY:
        log.error("RESEND_API_KEY not set — cannot send verification email")
        return False

    name       = entry.get("name") or "Collector"
    safe_name  = html_mod.escape(name)
    verify_url = f"{BASE_URL}/api/verify/{entry['verify_token']}"
    subject    = "Drop Watcher — Confirm your alerts"

    body_text = (
        f"Hey {name},\n\n"
        f"Confirm your Drop Watcher alerts:\n  {verify_url}\n\n"
        f"Once confirmed you will get alerted on matches.\n\n"
        f"HGR\ninstockornot.club\n"
    )
    body_html = (
        '<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:monospace;padding:24px;max-width:600px">' +
        '<h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>' +
        '<div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>' +
        f'<p style="color:#d0d0d0;font-size:16px">Hey {safe_name} — one click to confirm.</p>' +
        f'<div style="margin:24px 0"><a href="{verify_url}" style="background:#c0392b;color:#fff;padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:1px;display:inline-block">CONFIRM ALERTS</a></div>' +
        '<p style="color:#888;font-size:12px">If you did not sign up for Drop Watcher, ignore this email.</p>' +
        '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>' +
        '</body></html>'
    )

    try:
        r = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": FROM_ADDRESS, "to": [entry["email"]], "subject": subject,
                  "html": body_html, "text": body_text},
            timeout=15
        )
        r.raise_for_status()
        log.info(f"Verification email sent to {entry['email']} — id: {r.json().get('id')}")
        return True
    except Exception as e:
        log.error(f"Verification email failed for {entry['email']}: {e}")
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
        'verify_token':      str(uuid.uuid4()),  # one-time -- nulled after use
        'unsubscribe_token': str(uuid.uuid4()),  # permanent -- unguessable — unguessable
        'url':               data['url'].strip(),
        'keywords':          data['keywords'].strip(),
        'email':             data['email'].strip().lower(),
        'name':              data.get('name', '').strip(),
        'priority':          data.get('priority', 'high'),
        'phone':             data.get('phone', '').strip(),
        'sms_approved':      False,
        'active':            False,  # inactive until email verified
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
        # Resend verification if still pending
        if not existing[0].get('active') and existing[0].get('verify_token'):
            send_verification_email(existing[0])
        save_watchers(watchers)
        return jsonify({'status': 'updated', 'id': existing[0]['id']}), 200

    watchers.append(entry)
    save_watchers(watchers)
    log.info(f"New watcher: {entry['id']} | {entry['email']} | {entry['url']}")

    # Send verification email — non-blocking, failure doesn't break signup
    send_verification_email(entry)

    return jsonify({'status': 'created', 'id': entry['id']}), 201






@app.route('/api/resend-link', methods=['POST'])
def resend_link():
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email required'}), 400

    watchers = load_watchers()
    matches  = [w for w in watchers if w.get('email', '').lower() == email and w.get('active')]
    if not matches:
        # Return 200 regardless — don't leak whether email exists
        log.info(f"resend-link: no active watcher for {email}")
        return jsonify({'status': 'sent'})

    for w in matches:
        my_alerts_url = f"{BASE_URL}/my-alerts.html?token={w['unsubscribe_token']}"
        name          = w.get('name') or 'Collector'
        safe_name     = html_mod.escape(name)
        subject       = "Drop Watcher — Your alerts link"
        body_text     = (
            f"Hey {name},\n\n"
            f"Your personal Drop Watcher alerts page:\n  {my_alerts_url}\n\n"
            f"Bookmark it.\n\nHGR\ninstockornot.club\n"
        )
        body_html = (
            f'<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:monospace;padding:24px;max-width:600px">' +
            '<h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>' +
            '<div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>' +
            f'<p style="color:#d0d0d0;font-size:16px">Hey {safe_name} — your personal link.</p>' +
            f'<div style="margin:24px 0"><a href="{my_alerts_url}" style="background:#c0392b;color:#fff;padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:1px;display:inline-block">VIEW MY ALERTS</a></div>' +
            f'<p style="color:#888;font-size:12px;margin-top:16px">Or copy this URL:<br><a href="{my_alerts_url}" style="color:#e67e22">{my_alerts_url}</a></p>' +
            '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>' +
            '</body></html>'
        )
        try:
            r = httpx.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": FROM_ADDRESS, "to": [w["email"]], "subject": subject,
                      "html": body_html, "text": body_text},
                timeout=15
            )
            r.raise_for_status()
            log.info(f"resend-link sent to {email}")
        except Exception as e:
            log.error(f"resend-link failed for {email}: {e}")

    return jsonify({"status": "sent"})

@app.route('/api/my-watch/<token>', methods=['DELETE'])
def stop_watching(token):
    watchers = load_watchers()
    before   = len(watchers)
    watchers = [w for w in watchers if w.get('unsubscribe_token') != token]
    if len(watchers) == before:
        return jsonify({'error': 'not found'}), 404
    save_watchers(watchers)
    log.info(f"Watcher removed via token {token[:8]}")
    return jsonify({'status': 'removed'})

@app.route('/api/my-watch/<token>', methods=['GET'])
def my_watch(token):
    watchers = load_watchers()
    for w in watchers:
        if w.get('unsubscribe_token') == token:
            return jsonify({
                'email':    w.get('email'),
                'name':     w.get('name'),
                'url':      w.get('url'),
                'keywords': w.get('keywords'),
                'priority': w.get('priority'),
                'active':   w.get('active'),
                'created':  w.get('created'),
            })
    return jsonify({'error': 'not found'}), 404


@app.route('/api/my-alerts/<token>', methods=['GET'])
def my_alerts(token):
    import re
    watchers = load_watchers()
    watcher  = next((w for w in watchers if w.get('unsubscribe_token') == token), None)
    if not watcher:
        return jsonify({'error': 'not found'}), 404

    # Split on commas (not spaces) so multi-word keywords like "in stock" stay intact
    keywords = [k.strip().lower() for k in watcher.get('keywords', '').split(',') if k.strip()]
    watch_url  = watcher.get('url', '').lower()
    watch_domain = re.sub(r'^https?://(www\.)?', '', watch_url).split('/')[0]

    drops = []
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    drops_log = os.path.join(os.path.dirname(__file__), 'logs', 'drops.jsonl')
    try:
        with open(drops_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                # Skip drops older than 3 days
                if (d.get('timestamp') or '') < cutoff:
                    continue
                drop_url    = (d.get('url') or '').lower()
                drop_domain = re.sub(r'^https?://(www\.)?', '', drop_url).split('/')[0]
                summary     = (d.get('page_summary') or '').lower()
                notable     = ' '.join(d.get('notable_items') or []).lower()
                searchable  = f"{summary} {notable}"

                # Must match the watched domain
                if not watch_domain or watch_domain != drop_domain:
                    continue
                # Then check if any keyword appears in the drop content
                if keywords and not any(k in searchable for k in keywords):
                    continue
                drops.append(d)
    except FileNotFoundError:
        pass

    # newest first, cap at 50
    drops.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify({'watcher': watcher.get('email'), 'drops': drops[:50]})

@app.route('/api/verify/<token>', methods=['GET'])
def verify(token):
    watchers = load_watchers()
    for w in watchers:
        if w.get('verify_token') == token:
            if w.get('active'):
                return """<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#c0392b">DROP WATCHER</h1>
                    <p style="font-size:18px;margin-top:24px">Already verified.</p>
                    <p style="margin-top:32px"><a href="https://instockornot.club" style="color:#e67e22">instockornot.club</a></p>
                </body></html>""", 200
            w['active'] = True
            w['verify_token'] = None  # nulled after use — structure kept for audit
            save_watchers(watchers)
            log.info(f"Verified: {w['email']}")
            send_confirmation_email(w)  # welcome email — existing function
            my_alerts_url = f"{BASE_URL}/my-alerts.html?token={w['unsubscribe_token']}"
            return f"""<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#2ecc71">VERIFIED</h1>
                    <p style="font-size:18px;margin-top:24px;color:#f0f0f0">You are live. Alerts are active.</p>
                    <p style="margin-top:32px"><a href="{my_alerts_url}" style="color:#e67e22">VIEW MY ALERTS</a></p>
                    <div style="margin-top:24px;color:#c0392b;font-size:20px;font-weight:bold">HGR</div>
                </body></html>""", 200
    return """<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#888">DROP WATCHER</h1>
                    <p style="color:#888;font-size:14px;margin-top:24px">Link not found or already used.</p>
                </body></html>""", 404



@app.route('/api/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    watchers = load_watchers()
    for w in watchers:
        if w.get('unsubscribe_token') == token:
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


@app.route('/api/stats', methods=['GET'])
def stats():
    """Public stats endpoint — no PII, just counts and timestamps."""
    watchers = load_watchers()
    active_count = sum(1 for w in watchers if w.get('active'))

    drops_log = os.path.join(os.path.dirname(__file__), 'logs', 'drops.jsonl')
    total_drops = 0
    critical = 0
    high = 0
    medium = 0
    latest_ts = None
    from datetime import timedelta
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    drops_24h = 0

    try:
        with open(drops_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                total_drops += 1
                ts = d.get('timestamp', '')
                pri = (d.get('priority') or '').lower()
                if ts > cutoff_24h:
                    drops_24h += 1
                    if pri == 'critical':
                        critical += 1
                    elif pri == 'high':
                        high += 1
                    elif pri == 'medium':
                        medium += 1
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
    except FileNotFoundError:
        pass

    # Last preflight run
    preflight_log = os.path.join(os.path.dirname(__file__), 'logs', 'preflight.jsonl')
    last_preflight = None
    try:
        with open(preflight_log) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        p = json.loads(line)
                        last_preflight = p.get('timestamp')
                    except Exception:
                        pass
    except FileNotFoundError:
        pass

    return jsonify({
        'watchers_active': active_count,
        'drops_24h': drops_24h,
        'drops_total': total_drops,
        'critical_24h': critical,
        'high_24h': high,
        'medium_24h': medium,
        'latest_drop': latest_ts,
        'last_preflight': last_preflight,
    })


@app.route('/api/check-url', methods=['POST'])
def check_url():
    """Quick scrapeability check — called on URL blur from watchlist.html."""
    import requests
    from bs4 import BeautifulSoup
    from safe_fetch import is_safe_url

    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()

    if not url:
        return jsonify({'ok': False, 'msg': 'No URL provided.'}), 400

    if not url.startswith('http'):
        url = 'https://' + url

    # SSRF protection — block internal/private IPs
    safe, reason = is_safe_url(url)
    if not safe:
        return jsonify({'ok': False, 'msg': reason})

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; +https://instockornot.club)'
    }

    try:
        r = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
    except requests.exceptions.Timeout:
        return jsonify({'ok': False, 'msg': "That site took too long to respond. We won't be able to watch it reliably."})
    except requests.exceptions.ConnectionError:
        return jsonify({'ok': False, 'msg': "We can't reach that URL. Check the address and try again."})
    except Exception:
        return jsonify({'ok': False, 'msg': "Something went wrong reaching that URL."})

    # If redirect, validate the target too
    if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
        redirect_url = r.headers.get('Location', '')
        if redirect_url:
            safe, reason = is_safe_url(redirect_url)
            if not safe:
                return jsonify({'ok': False, 'msg': reason})
            try:
                r = requests.get(redirect_url, headers=headers, timeout=10, allow_redirects=False)
            except Exception:
                return jsonify({'ok': False, 'msg': "The redirect destination failed. Check the URL."})

    if r.status_code == 403:
        return jsonify({'ok': False, 'msg': "That site is blocking us (403 Forbidden). We won't be able to watch it."})
    if r.status_code == 429:
        return jsonify({'ok': False, 'msg': "That site is rate-limiting us. We won't be able to watch it reliably."})
    if r.status_code >= 400:
        return jsonify({'ok': False, 'msg': f"That page returned an error ({r.status_code}). Check the URL."})

    # Check if there's enough text content to scrape
    soup = BeautifulSoup(r.text, 'html.parser')
    for tag in soup(['nav', 'header', 'footer', 'script', 'style', 'meta', 'link']):
        tag.decompose()
    text = soup.get_text(separator=' ', strip=True)

    if len(text) < 200:
        return jsonify({'ok': False, 'msg': "That page doesn't have enough readable text. It may require JavaScript to load — we can't watch those yet."})

    return jsonify({'ok': True, 'msg': "We can read this page. You're good to go."})


@app.route('/api/watchers', methods=['GET'])
def list_watchers():
    """Admin endpoint — localhost only."""
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'forbidden'}), 403
    watchers = load_watchers()
    active = [w for w in watchers if w.get('active')]
    return jsonify({'count': len(active), 'watchers': active}), 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)
