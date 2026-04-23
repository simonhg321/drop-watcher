# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
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
import re
import secrets
import uuid
import logging
import httpx
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
CORS(app, origins=['https://instockornot.club'])
limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])

import paths
import db

load_dotenv(paths.ENV_FILE, override=True)

RESEND_API_KEY   = os.environ.get('RESEND_API_KEY')
FROM_ADDRESS     = 'Drop Watcher <info@instockornot.club>'
RESEND_API_URL   = 'https://api.resend.com/emails'
BASE_URL         = 'https://instockornot.club'

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ── URL normalization ────────────────────────────────────────────────────────

JUNK_PARAMS = {
    'gclid', 'gclsrc', 'gbraid', 'gad_source', 'gad_campaignid',
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
    'srsltid', 'tcid', 'wmlspartner', 'veh', 'cn', 'wl9', 'wl11',
    'sourceid', 'dclid', 'fbclid', 'msclkid', 'mc_cid', 'mc_eid',
}

def normalize_url(url):
    """Strip tracking/ad params from URL."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k.lower() not in JUNK_PARAMS}
    new_query = urlencode(cleaned, doseq=True) if cleaned else ''
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, ''
    ))


# ── Watcher database helpers ─────────────────────────────────────────────────
# All watcher state is now in SQLite via db.py


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
    if not re.match(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$', email) or len(email) > 254:
        return jsonify({'error': 'Invalid email address.'}), 400

    # URL: must be http(s), reasonable length, strip tracking params
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    url = normalize_url(url)
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

    # Deduplicate: same email + url combo
    existing = db.find_watcher_by_email_url(email, url)
    if existing:
        log.info(f"Duplicate watcher for {email} / {url} — updating keywords")
        db.update_watcher(existing['id'], keywords=keywords, priority=priority)
        if not existing.get('active'):
            vt = existing.get('verify_token') or str(uuid.uuid4())
            db.update_watcher(existing['id'], verify_token=vt)
            existing['verify_token'] = vt
            send_verification_email(existing)
        return jsonify({'status': 'updated', 'id': existing['id']}), 200

    # One token per email — reuse existing if this email already has watches
    email_watches = db.get_watchers_by_email(email)
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
        'sms_verify_code':   None,
        'sms_verify_expires': None,
        'active':            already_verified,  # auto-activate if email already verified
        'created':           datetime.now(timezone.utc).isoformat(),
        'last_alert':        None,
        'alert_count':       0,
    }

    db.add_watcher(entry)
    log.info(f"New watcher: {entry['id']} | {entry['email']} | {entry['url']} | reused_token={bool(email_watches)}")

    if already_verified:
        send_confirmation_email(entry)
    else:
        send_verification_email(entry)

    # SMS verification — send code if phone + consent provided
    sms_pending = bool(phone and data.get('sms_consent'))
    if sms_pending:
        code = f"{secrets.randbelow(900000) + 100000}"
        db.update_watcher(entry['id'],
            sms_verify_code=code,
            sms_verify_expires=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
        try:
            from sms_alerter import _send_twilio_sms
            _send_twilio_sms(phone, f"Drop Watcher verification code: {code}")
            log.info(f"SMS verification code sent to {phone}")
        except Exception as e:
            log.error(f"Failed to send SMS verification: {e}")

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

    if sms_pending:
        resp['sms_pending'] = True

    return jsonify(resp), 201






@app.route('/api/resend-link', methods=['POST'])
@limiter.limit("3 per minute")
def resend_link():
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email required'}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$', email) or len(email) > 254:
        return jsonify({'error': 'Invalid email address.'}), 400

    all_watches = db.get_watchers_by_email(email)
    matches = [w for w in all_watches if w.get('active')]
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
    token = request.args.get('token') or request.headers.get('X-Token')
    if not token:
        return jsonify({'error': 'unauthorized'}), 403
    target = db.get_watcher_by_id(watch_id)
    if not target:
        return jsonify({'error': 'not found'}), 404
    import hmac
    if not hmac.compare_digest(target.get('unsubscribe_token', ''), token):
        return jsonify({'error': 'unauthorized'}), 403
    db.delete_watcher(watch_id)
    log.info(f"Watcher removed: {watch_id}")
    return jsonify({'status': 'removed'})

@app.route('/api/my-watch/<token>', methods=['GET'])
@limiter.limit("10 per minute")
def my_watch(token):
    w = db.get_watcher_by_unsub_token(token)
    if not w:
        return jsonify({'error': 'not found'}), 404
    return jsonify({
        'email':    w.get('email'),
        'name':     w.get('name'),
        'url':      w.get('url'),
        'keywords': w.get('keywords'),
        'priority': w.get('priority'),
        'active':   bool(w.get('active')),
        'created':  w.get('created'),
    })


@app.route('/api/my-alerts/<token>', methods=['GET'])
@limiter.limit("10 per minute")
def my_alerts(token):
    import re
    watcher = db.get_watcher_by_unsub_token(token)
    if not watcher:
        return jsonify({'error': 'not found'}), 404

    # Find ALL watches for this email
    email = watcher.get('email', '').lower()
    all_watches = db.get_watchers_by_email(email)
    my_watches = [w for w in all_watches if w.get('active')]

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

    recent_drops = db.get_recent_drops(hours=72)
    matched_drops = []
    for d in recent_drops:
        drop_url    = (d.get('url') or '').lower()
        drop_domain = re.sub(r'^https?://(www\.)?', '', drop_url).split('/')[0]
        summary     = (d.get('page_summary') or '').lower()
        notable     = ' '.join(d.get('notable_items') or []).lower()
        searchable  = f"{summary} {notable}"

        for wf in watch_filters:
            if not wf['domain'] or wf['domain'] != drop_domain:
                continue
            if wf['keywords'] and not any(k in searchable for k in wf['keywords']):
                continue
            matched_drops.append(d)
            break

    matched_drops.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify({
        'watcher': watcher.get('email'),
        'watches': watch_filters,
        'drops': matched_drops[:50]
    })

@app.route('/api/verify/<token>', methods=['GET'])
@limiter.limit("10 per minute")
def verify(token):
    w = db.get_watcher_by_verify_token(token)
    if not w:
        return """<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#888">DROP WATCHER</h1>
                    <p style="color:#888;font-size:14px;margin-top:24px">Link not found or already used.</p>
                </body></html>""", 404

    if w.get('active'):
        return """<html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#c0392b">DROP WATCHER</h1>
                    <p style="font-size:18px;margin-top:24px">Already verified.</p>
                    <p style="margin-top:32px"><a href="https://instockornot.club" style="color:#e67e22">instockornot.club</a></p>
                </body></html>""", 200

    # Activate ALL watches for this email
    verified_email = w.get('email', '').lower()
    db.update_watchers_by_email(verified_email, active=True, verify_token=None)
    log.info(f"Verified: {w['email']} — activated all watches for this email")
    send_confirmation_email(w)

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
                    <div style="margin-top:24px;color:#c0392b;font-size:20px;font-weight:bold">SGH</div>
                    <button onclick="new Audio('/audio/dropwatcher.mp3').play();this.style.display='none'" style="margin-top:24px;background:none;border:1px solid #888;color:#888;padding:8px 16px;cursor:pointer;font-family:monospace;font-size:11px;letter-spacing:2px">&#9835; PLAY</button>
                </body></html>""", 200



@app.route('/api/verify-phone', methods=['POST'])
@limiter.limit("10 per minute")
def verify_phone():
    """Verify SMS phone number with 6-digit code sent on signup."""
    data = request.get_json(force=True)
    watch_id = data.get('id', '').strip()
    code     = data.get('code', '').strip()

    if not watch_id or not code:
        return jsonify({'error': 'Missing id or code'}), 400

    w = db.get_watcher_by_id(watch_id)
    if w and w.get('sms_verify_code') == code:
        expires = w.get('sms_verify_expires', '')
        if expires and datetime.now(timezone.utc).isoformat() > expires:
            return jsonify({'error': 'Code expired. Sign up again to get a new code.'}), 410
        db.update_watcher(watch_id,
            sms_approved=True, sms_verify_code=None, sms_verify_expires=None)
        log.info(f"Phone verified for {w['email']}")
        return jsonify({'status': 'verified'})

    return jsonify({'error': 'Invalid code'}), 400


@app.route('/api/pageview', methods=['POST'])
@limiter.limit("60 per minute")
def track_pageview():
    """Anonymous pageview tracking — cookie-based visitor ID."""
    data = request.get_json(silent=True) or {}
    vid  = data.get('vid', '')[:16]
    path = data.get('path', '')[:200]
    ref  = data.get('ref', '')[:500]

    if not vid or not path:
        return '', 204

    try:
        db.add_pageview(vid, path, ref, request.remote_addr)
    except Exception:
        pass

    return '', 204


@app.route('/api/ack/<token>', methods=['GET'])
@limiter.limit("20 per minute")
def ack_watch(token):
    """Keep-alive click from an alert email — marks user engaged, cancels any pending age-out."""
    w = db.get_watcher_by_unsub_token(token)
    if not w:
        return jsonify({'error': 'Not found'}), 404

    email = w.get('email', '').lower()
    now = datetime.now(timezone.utc).isoformat()
    # Reactivate only watches that age-out turned off. ageout_email_sent IS NOT NULL
    # distinguishes age-out victims from unsubscribes or unverified signups.
    revived = db.revive_aged_out(email, now)
    db.update_watchers_by_email(email, last_acked=now, ageout_email_sent=None)
    if revived:
        log.info(f"Ack from {email} — revived {revived} aged-out watch(es)")
    else:
        log.info(f"Ack from {email} — cleared pending age-out")

    return """
            <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                <h1 style="color:#27ae60">DROP WATCHER</h1>
                <p style="font-size:18px;margin-top:24px">✓ Watch kept alive.</p>
                <p style="color:#888;font-size:13px">Thanks — we'll keep sending you alerts.</p>
                <p style="margin-top:32px"><a href="https://instockornot.club" style="color:#e67e22">instockornot.club</a></p>
            </body></html>""", 200


@app.route('/api/unsubscribe/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def unsubscribe(token):
    w = db.get_watcher_by_unsub_token(token)
    if not w:
        return jsonify({'error': 'Not found'}), 404

    email = w.get('email', '').lower()
    all_watches = db.get_watchers_by_email(email)
    any_active = any(ww.get('active') for ww in all_watches)
    if not any_active:
        return jsonify({'status': 'already_unsubscribed'}), 200

    db.update_watchers_by_email(email, active=False)
    count = sum(1 for ww in all_watches if ww.get('active'))
    log.info(f"Unsubscribed: {email} — deactivated {count} watches")

    if request.method == 'GET':
        return """
                <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:48px;text-align:center">
                    <h1 style="color:#c0392b">DROP WATCHER</h1>
                    <p style="font-size:18px;margin-top:24px">You've been unsubscribed.</p>
                    <p style="color:#888;font-size:13px">You won't receive any more alerts from us.</p>
                    <p style="margin-top:32px"><a href="https://instockornot.club" style="color:#e67e22">instockornot.club</a></p>
                </body></html>""", 200
    return jsonify({'status': 'unsubscribed'}), 200


@app.route('/api/stats', methods=['GET'])
def stats():
    """Public stats endpoint — no PII, just counts and timestamps."""
    active_count = db.count_active_watchers()
    total_drops = db.get_drops_count()
    drops_24h = db.get_drops_count(hours=24)
    by_priority = db.get_drops_by_priority(hours=24)
    latest_ts = db.get_latest_drop_timestamp()

    # Last preflight run — still from JSONL (not migrated, it's diagnostic)
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

    # Watchdog status — still from JSON (not migrated, it's diagnostic)
    watchdog_state = {}
    try:
        with open(paths.WATCHDOG_STATE) as f:
            watchdog_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

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
                if '[watchdog]' in last_line:
                    last_watchdog = last_line.split(' [watchdog]')[0].strip()
    except FileNotFoundError:
        pass

    return jsonify({
        'watchers_active': active_count,
        'drops_24h': drops_24h,
        'drops_total': total_drops,
        'critical_24h': by_priority.get('critical', 0),
        'high_24h': by_priority.get('high', 0),
        'medium_24h': by_priority.get('medium', 0),
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
    url = normalize_url(url)

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

    # Homepage nudge — no path means they're watching a landing page, not a product
    from urllib.parse import urlparse
    parsed = urlparse(url)
    warning = None
    if parsed.path in ('', '/'):
        warning = "Heads up — this looks like a homepage. A direct product or search page gets better results."

    resp = {'ok': True, 'msg': "We can read this page. You're good to go."}
    if warning:
        resp['warning'] = warning
    return jsonify(resp)


# ── NKD (New Knife Day) — conversion tracking ────────────────────────────────

import nkd


@app.route('/api/nkd/<token>', methods=['GET'])
@limiter.limit("30 per hour")
def nkd_info(token):
    """Validate a NKD token and return watcher/drop context for the landing page."""
    data = nkd.verify_token(token)
    if not data:
        return jsonify({'ok': False, 'msg': 'Link expired or invalid.'}), 400

    watcher = db.get_watcher_by_id(data['w'])
    if not watcher:
        return jsonify({'ok': False, 'msg': 'Watcher not found.'}), 404

    already = nkd.already_scored(data['w'], data['d'])

    return jsonify({
        'ok': True,
        'name': (watcher.get('name') or '').strip() or None,
        'keywords': watcher.get('keywords', ''),
        'drop_url': data['u'],
        'already_scored': already,
    })


@app.route('/api/nkd/<token>', methods=['POST'])
@limiter.limit("10 per hour")
def nkd_submit(token):
    """Record a score. Body: {note, image_url, show_on_wall, drop_url}."""
    data = nkd.verify_token(token)
    if not data:
        return jsonify({'ok': False, 'msg': 'Link expired or invalid.'}), 400

    body = request.get_json(silent=True) or {}
    note = (body.get('note') or '').strip()
    image_url = (body.get('image_url') or '').strip()
    show_on_wall = 1 if body.get('show_on_wall') else 0

    if image_url:
        if len(image_url) > 500 or not image_url.startswith(('http://', 'https://')):
            return jsonify({'ok': False, 'msg': 'Image URL must be http(s) and under 500 chars.'}), 400

    if nkd.already_scored(data['w'], data['d']):
        return jsonify({'ok': False, 'msg': 'Already recorded. Thanks!'}), 409

    nkd.record_score(
        watcher_id=data['w'],
        drop_url=data['u'],
        note=note,
        image_url=image_url,
        show_on_wall=show_on_wall,
    )
    return jsonify({'ok': True})


@app.route('/api/nkd/wall', methods=['GET'])
@limiter.limit("60 per hour")
def nkd_wall():
    """Public wins wall — only show_on_wall=1 entries."""
    return jsonify({'ok': True, 'entries': nkd.get_wall_entries(limit=50)})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)
