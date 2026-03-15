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

import fcntl
import html as html_mod
import json
import os
import re
import uuid
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
CORS(app, origins=['https://instockornot.club'])
limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])

import paths
WATCHERS_FILE = paths.WATCHERS_JSON

load_dotenv(paths.ENV_FILE, override=True)

RESEND_API_KEY   = os.environ.get('RESEND_API_KEY')
FROM_ADDRESS     = 'Drop Watcher <info@instockornot.club>'
RESEND_API_URL   = 'https://api.resend.com/emails'
BASE_URL         = 'https://instockornot.club'

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ── Watchers file helpers (with file locking) ────────────────────────────────

LOCK_FILE = WATCHERS_FILE + '.lock'

def load_watchers():
    if not os.path.exists(WATCHERS_FILE):
        return []
    with open(WATCHERS_FILE) as f:
        fcntl.flock(f, fcntl.LOCK_SH)  # shared lock for reads
        data = json.load(f)
        fcntl.flock(f, fcntl.LOCK_UN)
        return data


def save_watchers(watchers):
    os.makedirs(os.path.dirname(WATCHERS_FILE), exist_ok=True)
    lock_fd = open(LOCK_FILE, 'w')
    fcntl.flock(lock_fd, fcntl.LOCK_EX)  # exclusive lock for writes
    try:
        # Write to temp file then rename — atomic on same filesystem
        tmp = WATCHERS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(watchers, f, indent=2)
        os.replace(tmp, WATCHERS_FILE)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


# ── Quick keyword check ──────────────────────────────────────────────────────

def quick_keyword_check(url, keywords_str):
    """Fetch a page and check for keyword matches. Returns list of matched keywords."""
    import requests as req
    from bs4 import BeautifulSoup
    from safe_fetch import is_safe_url

    safe, _ = is_safe_url(url)
    if not safe:
        return []

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; +https://instockornot.club)'}
        r = req.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(['nav', 'footer', 'script', 'style', 'header']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True).lower()
    except Exception:
        return []

    keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
    return [kw for kw in keywords if kw in text]


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

    my_alerts_url = f"{BASE_URL}/my-alerts.html?token={entry['unsubscribe_token']}"

    body_text = f"""Hey {name},

You're now watching:
  URL: {url}
  Keywords: {keywords}

HOW THIS WORKS:
  1. We check your page every 30 minutes for your keywords.
  2. When we find a match, we email you immediately.
  3. Your personal dashboard: {my_alerts_url}
     Bookmark it — this is where you see all your matched drops.
  4. Lost this link? Go to instockornot.club/get-my-link and we'll resend it.

To stop watching: {unsubscribe_url}

HGR
instockornot.club
"""

    body_html = f"""
    <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:24px;max-width:600px">
        <h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>
        <div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>

        <p style="color:#d0d0d0;font-size:16px">Hey {safe_name}, you're set up.</p>

        <div style="text-align:center;margin:28px 0">
            <a href="{my_alerts_url}" style="display:inline-block;background:#e67e22;color:#fff;padding:16px 32px;text-decoration:none;font-size:14px;letter-spacing:2px;">VIEW MY ALERTS</a>
        </div>

        <div style="background:#1c1c1c;padding:16px;margin:20px 0">
            <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:8px">WATCHING</div>
            <div style="margin-top:8px">
                <span style="color:#888;font-size:11px">KEYWORDS</span><br>
                <span style="color:#f0f0f0;font-size:14px">{safe_keywords}</span>
            </div>
            <div style="margin-top:12px">
                <span style="color:#888;font-size:11px">PAGE</span><br>
                <a href="{safe_url}" style="color:#e67e22;font-size:13px;word-break:break-all">{safe_url}</a>
            </div>
        </div>

        <div style="background:#1c1c1c;padding:16px;margin:20px 0">
            <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:12px">HOW THIS WORKS</div>
            <div style="color:#d0d0d0;font-size:13px;line-height:1.8">
                <span style="color:#e67e22">1.</span> We check your page every 30 minutes for your keywords.<br>
                <span style="color:#e67e22">2.</span> When we find a match, we email you immediately.<br>
                <span style="color:#e67e22">3.</span> Your personal dashboard is the link below — bookmark it.<br>
                <span style="color:#e67e22">4.</span> Lost the link? Visit <a href="{BASE_URL}/get-my-link.html" style="color:#e67e22">instockornot.club/get-my-link</a> to get it back.
            </div>
        </div>

        <div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#888;font-size:11px;letter-spacing:2px;text-align:center">
            <div style="color:#c0392b;font-size:16px;font-weight:bold;margin-bottom:8px">HGR</div>
            <a href="{unsubscribe_url}" style="color:#555;font-size:11px">Unsubscribe</a>
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
        f"Once confirmed, we'll start watching your page every 30 minutes.\n"
        f"When your keywords show up, you'll get an email immediately.\n\n"
        f"HGR\ninstockornot.club\n"
    )
    body_html = (
        '<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:monospace;padding:24px;max-width:600px">' +
        '<h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>' +
        '<div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>' +
        f'<p style="color:#d0d0d0;font-size:16px">Hey {safe_name} — one click to confirm.</p>' +
        f'<div style="text-align:center;margin:24px 0"><a href="{verify_url}" style="background:#c0392b;color:#fff;padding:16px 32px;text-decoration:none;font-size:14px;letter-spacing:2px;display:inline-block">CONFIRM ALERTS</a></div>' +
        '<p style="color:#888;font-size:13px;line-height:1.7">Once confirmed, we start watching your page every 30 minutes. When your keywords appear, you get an email right away.</p>' +
        '<p style="color:#888;font-size:12px;margin-top:12px">If you did not sign up for Drop Watcher, ignore this email.</p>' +
        '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;text-align:center;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>' +
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
@limiter.limit("5 per minute")
def watch():
    data = request.get_json(force=True)

    # Validate required fields
    for field in ['url', 'keywords', 'email']:
        if not data.get(field, '').strip():
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # ── Input validation ─────────────────────────────────────────────────────
    email = data['email'].strip().lower()
    url   = data['url'].strip()
    keywords = data['keywords'].strip()
    name  = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    priority = data.get('priority', 'high')

    # Email format
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) or len(email) > 254:
        return jsonify({'error': 'Invalid email address.'}), 400

    # URL: must be http(s), reasonable length
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    if len(url) > 2048:
        return jsonify({'error': 'URL is too long (max 2048 chars).'}), 400

    # Keywords: reasonable length
    if len(keywords) > 1000:
        return jsonify({'error': 'Keywords too long (max 1000 chars).'}), 400

    # Name: optional, cap length
    if len(name) > 100:
        return jsonify({'error': 'Name too long (max 100 chars).'}), 400

    # Priority: whitelist
    if priority not in ('critical', 'high', 'medium', 'low'):
        priority = 'high'

    # Phone: digits, plus, dashes, spaces, parens only
    if phone and not re.match(r'^[\d\s\+\-\(\)]{7,20}$', phone):
        return jsonify({'error': 'Invalid phone number format.'}), 400

    watchers = load_watchers()

    # Deduplicate: same email + url combo
    existing = [w for w in watchers if w['email'] == email and w['url'] == url]
    if existing:
        log.info(f"Duplicate watcher for {email} / {url} — updating keywords")
        existing[0]['keywords'] = keywords
        existing[0]['priority'] = priority
        if not existing[0].get('active'):
            if not existing[0].get('verify_token'):
                existing[0]['verify_token'] = str(uuid.uuid4())
            send_verification_email(existing[0])
        save_watchers(watchers)
        return jsonify({'status': 'updated', 'id': existing[0]['id']}), 200

    # One token per email — reuse existing if this email already has watches
    email_watches = [w for w in watchers if w.get('email', '').lower() == email]
    if email_watches:
        shared_token = email_watches[0]['unsubscribe_token']
        already_verified = any(w.get('active') for w in email_watches)
    else:
        shared_token = str(uuid.uuid4())
        already_verified = False

    entry = {
        'id':                str(uuid.uuid4())[:8],
        'verify_token':      None if already_verified else str(uuid.uuid4()),
        'unsubscribe_token': shared_token,
        'url':               url,
        'keywords':          keywords,
        'email':             email,
        'name':              name,
        'priority':          priority,
        'phone':             phone,
        'sms_approved':      False,
        'active':            already_verified,  # auto-activate if email already verified
        'created':           datetime.now(timezone.utc).isoformat(),
        'last_alert':        None,
        'alert_count':       0,
    }

    watchers.append(entry)
    save_watchers(watchers)
    log.info(f"New watcher: {entry['id']} | {entry['email']} | {entry['url']} | reused_token={bool(email_watches)}")

    if already_verified:
        # Email already verified — send welcome email, skip verification
        send_confirmation_email(entry)
    else:
        # First watch for this email — send verification
        send_verification_email(entry)

    # Quick keyword preview — show user what we found right now
    matches = quick_keyword_check(url, keywords)
    resp = {'status': 'created', 'id': entry['id']}
    if matches:
        resp['preview'] = matches
        if already_verified:
            resp['preview_msg'] = f"We already see {len(matches)} keyword match{'es' if len(matches) != 1 else ''} on that page. Alert incoming."
        else:
            resp['preview_msg'] = f"We already see {len(matches)} keyword match{'es' if len(matches) != 1 else ''} on that page. You'll get alerted once you verify your email."
    else:
        if already_verified:
            resp['preview_msg'] = "No matches yet — you're live, we'll alert you when something hits."
        else:
            resp['preview_msg'] = "No matches yet — we'll keep watching and alert you when something hits."

    return jsonify(resp), 201






@app.route('/api/resend-link', methods=['POST'])
@limiter.limit("3 per minute")
def resend_link():
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email required'}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) or len(email) > 254:
        return jsonify({'error': 'Invalid email address.'}), 400

    watchers = load_watchers()
    matches  = [w for w in watchers if w.get('email', '').lower() == email and w.get('active')]
    if not matches:
        # Return 200 regardless — don't leak whether email exists
        log.info(f"resend-link: no active watcher for {email}")
        return jsonify({'status': 'sent'})

    # All watches share same token — just send one email
    w = matches[0]
    if True:
        my_alerts_url = f"{BASE_URL}/my-alerts.html?token={w['unsubscribe_token']}"
        name          = w.get('name') or 'Collector'
        safe_name     = html_mod.escape(name)
        subject       = "Drop Watcher — Your alerts link"
        body_text     = (
            f"Hey {name},\n\n"
            f"Your personal Drop Watcher dashboard:\n  {my_alerts_url}\n\n"
            f"Bookmark this link — it's how you check your alerts.\n"
            f"We check your page every 30 minutes. When your keywords show up, we email you.\n\n"
            f"HGR\ninstockornot.club\n"
        )
        body_html = (
            f'<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:monospace;padding:24px;max-width:600px">' +
            '<h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>' +
            '<div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>' +
            f'<p style="color:#d0d0d0;font-size:16px">Hey {safe_name} — here is your personal link.</p>' +
            '<p style="color:#888;font-size:13px;line-height:1.7;margin:16px 0">This is your alerts dashboard. Bookmark it — it shows all your matched drops and your watcher status. We check your page every 30 minutes and email you when your keywords show up.</p>' +
            f'<div style="text-align:center;margin:24px 0"><a href="{my_alerts_url}" style="display:inline-block;background:#e67e22;color:#fff;padding:16px 32px;text-decoration:none;font-size:14px;letter-spacing:2px;">VIEW MY ALERTS</a></div>' +
            f'<p style="color:#555;font-size:11px;margin-top:16px;word-break:break-all">{my_alerts_url}</p>' +
            '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;text-align:center;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>' +
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

@app.route('/api/my-watch/<watch_id>', methods=['DELETE'])
def stop_watching(watch_id):
    watchers = load_watchers()
    before   = len(watchers)
    watchers = [w for w in watchers if w.get('id') != watch_id]
    if len(watchers) == before:
        return jsonify({'error': 'not found'}), 404
    save_watchers(watchers)
    log.info(f"Watcher removed: {watch_id}")
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

    # Find ALL watches for this email
    email = watcher.get('email', '').lower()
    my_watches = [w for w in watchers if w.get('email', '').lower() == email and w.get('active')]

    # Build list of (domain, keywords) pairs across all watches
    watch_filters = []
    for w in my_watches:
        kws = [k.strip().lower() for k in w.get('keywords', '').split(',') if k.strip()]
        url = w.get('url', '').lower()
        domain = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
        watch_filters.append({'domain': domain, 'keywords': kws, 'url': url,
                              'keywords_raw': w.get('keywords', ''),
                              'id': w.get('id'),
                              'token': w.get('unsubscribe_token')})

    drops = []
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    drops_log = paths.DROPS_JSONL
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
                if (d.get('timestamp') or '') < cutoff:
                    continue
                drop_url    = (d.get('url') or '').lower()
                drop_domain = re.sub(r'^https?://(www\.)?', '', drop_url).split('/')[0]
                summary     = (d.get('page_summary') or '').lower()
                notable     = ' '.join(d.get('notable_items') or []).lower()
                searchable  = f"{summary} {notable}"

                # Match against ANY of the user's watches
                for wf in watch_filters:
                    if not wf['domain'] or wf['domain'] != drop_domain:
                        continue
                    if wf['keywords'] and not any(k in searchable for k in wf['keywords']):
                        continue
                    drops.append(d)
                    break  # don't double-add
    except FileNotFoundError:
        pass

    drops.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify({
        'watcher': watcher.get('email'),
        'watches': watch_filters,
        'drops': drops[:50]
    })

@app.route('/api/verify/<token>', methods=['GET'])
@limiter.limit("10 per minute")
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
            # Activate ALL watches for this email
            verified_email = w.get('email', '').lower()
            for ww in watchers:
                if ww.get('email', '').lower() == verified_email:
                    ww['active'] = True
                    ww['verify_token'] = None
            save_watchers(watchers)
            log.info(f"Verified: {w['email']} — activated all watches for this email")
            send_confirmation_email(w)  # welcome email

            # Quick preview check — show on verify page only, no alert or drop written
            # Real alerts come from the AI pipeline (web_watcher → ai_interpreter → per_user_alerter)
            matches = quick_keyword_check(w['url'], w['keywords'])
            match_msg = ''
            if matches:
                log.info(f"Verify-check: {len(matches)} potential matches for {w['email']}: {matches}")
                match_msg = f'<p style="color:#2ecc71;font-size:14px;margin-top:16px">We see potential matches for: {html_mod.escape(", ".join(matches))}. The AI pipeline will confirm and alert you.</p>'

            my_alerts_url = f"{BASE_URL}/my-alerts.html?token={w['unsubscribe_token']}"
            return f"""<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#2ecc71">VERIFIED</h1>
                    <p style="font-size:18px;margin-top:24px;color:#f0f0f0">You are live. Alerts are active.</p>
                    {match_msg}
                    <p style="margin-top:32px"><a href="{my_alerts_url}" style="display:inline-block;background:#e67e22;color:#fff;padding:16px 32px;text-decoration:none;font-size:16px;letter-spacing:2px;">VIEW MY ALERTS</a></p>
                    <div style="margin-top:24px;color:#c0392b;font-size:20px;font-weight:bold">HGR</div>
                </body></html>""", 200
    return """<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#888">DROP WATCHER</h1>
                    <p style="color:#888;font-size:14px;margin-top:24px">Link not found or already used.</p>
                </body></html>""", 404



@app.route('/api/unsubscribe/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def unsubscribe(token):
    watchers = load_watchers()
    for w in watchers:
        if w.get('unsubscribe_token') == token:
            email = w.get('email', '').lower()
            any_active = any(ww.get('active') for ww in watchers if ww.get('email', '').lower() == email)
            if not any_active:
                return jsonify({'status': 'already_unsubscribed'}), 200
            # Deactivate ALL watches for this email
            count = 0
            for ww in watchers:
                if ww.get('email', '').lower() == email and ww.get('active'):
                    ww['active'] = False
                    count += 1
            save_watchers(watchers)
            log.info(f"Unsubscribed: {email} — deactivated {count} watches")
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

    drops_log = paths.DROPS_JSONL
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
    preflight_log = paths.PREFLIGHT_JSONL
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

    # Watchdog status
    watchdog_state = {}
    watchdog_log = paths.WATCHDOG_STATE
    try:
        with open(watchdog_log) as f:
            watchdog_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Last watchdog run time — read last line of watchdog.log
    last_watchdog = None
    watchdog_logfile = os.path.join(paths.LOG_DIR, 'watchdog.log')
    try:
        with open(watchdog_logfile, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            pos = max(0, size - 512)
            f.seek(pos)
            lines = f.read().decode(errors='replace').strip().split('\n')
            if lines:
                last_line = lines[-1]
                # Extract timestamp from "2026-03-14 16:30:00 [watchdog]..."
                if '[watchdog]' in last_line:
                    last_watchdog = last_line.split(' [watchdog]')[0].strip()
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
        'watchdog_failures': watchdog_state,
        'last_watchdog': last_watchdog,
    })


@app.route('/api/check-url', methods=['POST'])
@limiter.limit("10 per minute")
def check_url():
    """Quick scrapeability check — called on URL blur from watchlist.html."""
    import requests
    from bs4 import BeautifulSoup
    from safe_fetch import is_safe_url

    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()

    if not url:
        return jsonify({'ok': False, 'msg': 'No URL provided.'}), 400
    if len(url) > 2048:
        return jsonify({'ok': False, 'msg': 'URL is too long.'}), 400

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
