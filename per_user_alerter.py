# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
per_user_alerter.py — Routes alerts to public watchers based on watchers.json

Runs as a cron job: */10 * * * * python3 /home/shg/drop-watcher/per_user_alerter.py

For each active watcher:
  1. Reads recent drops from drops.jsonl (written by web_watcher/feed_watcher)
  2. Matches drops against watcher URL domain + keywords
  3. If match found AND not recently alerted for that URL+keyword → sends email

Does NOT re-scrape sites — web_watcher already does that.
Cooldown is per watcher per URL per matched keyword set, not per watcher globally.
HGR
"""

import fcntl
import hashlib
import html as html_mod
import json
import os
import re
import logging
from datetime import datetime, timezone, timedelta

import paths
WATCHERS_FILE = paths.WATCHERS_JSON
COOLDOWN_HOURS = 6
DROPS_WINDOW_MINUTES = 15  # Only look at drops from last N minutes (aligns with cron)

from alerter import send_email

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [per_user_alerter] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

LOCK_FILE = WATCHERS_FILE + '.lock'

# Track what we've already alerted per watcher — persists across runs
SENT_FILE = os.path.join(paths.DATA_DIR, 'per_user_sent.json')


def load_watchers():
    if not os.path.exists(WATCHERS_FILE):
        return []
    with open(WATCHERS_FILE) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        data = json.load(f)
        fcntl.flock(f, fcntl.LOCK_UN)
        return data


def save_watchers(watchers):
    lock_fd = open(LOCK_FILE, 'w')
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        tmp = WATCHERS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(watchers, f, indent=2)
        os.replace(tmp, WATCHERS_FILE)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def load_sent():
    """Load sent tracking: {cooldown_key: iso_timestamp}"""
    try:
        with open(SENT_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_sent(sent):
    os.makedirs(os.path.dirname(SENT_FILE), exist_ok=True)
    tmp = SENT_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(sent, f, indent=2)
    os.replace(tmp, SENT_FILE)


def prune_sent(sent):
    """Remove entries older than 24h to keep file small."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return {k: v for k, v in sent.items() if v > cutoff}


def cooldown_key(watcher_id, drop_url, matches):
    """Unique key per watcher + drop URL + matched keywords."""
    match_str = ','.join(sorted(matches))
    raw = f"{watcher_id}|{drop_url}|{match_str}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_recent_drops():
    """Read drops from last DROPS_WINDOW_MINUTES minutes."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=DROPS_WINDOW_MINUTES)).isoformat()
    drops = []
    try:
        with open(paths.DROPS_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if (d.get('timestamp') or '') >= cutoff:
                    drops.append(d)
    except FileNotFoundError:
        pass
    return drops


def domain_from_url(url):
    return re.sub(r'^https?://(www\.)?', '', url.lower()).split('/')[0]


def keywords_match(searchable_text, keywords_str):
    """Returns list of matched keywords."""
    keywords = [k.strip().lower() for k in re.split(r'[,\n]+', keywords_str) if k.strip()]
    return [kw for kw in keywords if kw in searchable_text]


def build_alert_email(watcher, matches, drop):
    name = watcher.get('name') or 'Watcher'
    url = drop.get('url', '')
    subject = f"[DROP WATCHER] Match found — {drop.get('source', url[:40])}"

    safe_name    = html_mod.escape(name)
    safe_url     = html_mod.escape(url)
    safe_matches = [html_mod.escape(m) for m in matches]
    unsub_token  = watcher['unsubscribe_token']
    summary      = html_mod.escape(drop.get('page_summary', ''))
    notable      = drop.get('notable_items', [])
    safe_notable = [html_mod.escape(n) for n in notable[:5]]
    priority     = html_mod.escape(drop.get('priority', 'medium'))

    notable_html = ''
    if safe_notable:
        items = ''.join(f'<li style="color:#e8e8e8;margin:4px 0">{n}</li>' for n in safe_notable)
        notable_html = f'''
      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Notable items</div>
        <ul style="margin:0;padding-left:20px">{items}</ul>
      </div>'''

    email_html = f"""
    <div style="font-family: monospace; background: #0a0a0a; color: #e8e8e8; padding: 24px; max-width: 600px;">
      <h2 style="color: #ff2d2d; margin: 0 0 16px;">⚡ DROP WATCHER</h2>
      <p style="color: #aaa; margin: 0 0 20px; font-size: 13px;">instockornot.club</p>

      <p>Hey {safe_name} — we found a match on a page you're watching.</p>

      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Source</div>
        <a href="{safe_url}" style="color: #ff6b2b;">{html_mod.escape(drop.get('source', ''))}</a>
        <div style="color:#888;font-size:12px;margin-top:8px">{summary}</div>
      </div>

      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Keywords matched</div>
        <div style="color: #e8e8e8;">{'  ·  '.join(safe_matches)}</div>
      </div>

      {notable_html}

      <p style="margin: 20px 0 0;">
        <a href="{safe_url}" style="background: #ff2d2d; color: white; padding: 12px 24px; text-decoration: none; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;">View Page Now →</a>
      </p>

      <p style="margin: 16px 0 0;">
        <a href="https://instockornot.club/my-alerts.html?token={unsub_token}" style="background: #e67e22; color: white; padding: 10px 20px; text-decoration: none; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;">My Alerts Dashboard</a>
      </p>

      <hr style="border: none; border-top: 1px solid #222; margin: 32px 0;">
      <p style="color: #444; font-size: 11px;">
        <a href="https://instockornot.club/api/unsubscribe/{unsub_token}" style="color: #444;">Unsubscribe</a> · instockornot.club
      </p>
    </div>
    """

    text = (
        f"DROP WATCHER — Match found\n\n"
        f"Source: {drop.get('source', '')}\n"
        f"Page: {url}\n"
        f"Matched: {', '.join(matches)}\n"
        f"Summary: {drop.get('page_summary', '')}\n\n"
        f"View: {url}\n\n"
        f"Dashboard: https://instockornot.club/my-alerts.html?token={unsub_token}\n"
        f"Unsubscribe: https://instockornot.club/api/unsubscribe/{unsub_token}"
    )

    return subject, email_html, text


def run():
    watchers = load_watchers()
    active = [w for w in watchers if w.get('active')]
    log.info(f"Checking {len(active)} active watchers against recent drops")

    if not active:
        log.info("No active watchers. Done.")
        return

    drops = load_recent_drops()
    log.info(f"Found {len(drops)} drops in last {DROPS_WINDOW_MINUTES} minutes")

    if not drops:
        log.info("No recent drops. Done.")
        return

    sent = load_sent()
    sent = prune_sent(sent)
    changed = False
    sent_changed = False
    now = datetime.now(timezone.utc)
    cooldown_cutoff = (now - timedelta(hours=COOLDOWN_HOURS)).isoformat()

    # Group watchers by email to avoid duplicate emails
    email_alerts = {}  # email -> list of (watcher, matches, drop)

    for watcher in active:
        wid   = watcher['id']
        w_url = watcher.get('url', '').lower()
        w_domain = domain_from_url(w_url)
        kws   = watcher.get('keywords', '')
        email = watcher['email']

        for drop in drops:
            drop_url    = (drop.get('url') or '').lower()
            drop_domain = domain_from_url(drop_url)

            # Domain must match
            if not w_domain or w_domain != drop_domain:
                continue

            # Build searchable text from drop
            summary  = (drop.get('page_summary') or '').lower()
            notable  = ' '.join(drop.get('notable_items') or []).lower()
            searchable = f"{summary} {notable}"

            matches = keywords_match(searchable, kws)
            if not matches:
                continue

            # Check per-URL-per-keyword cooldown
            ck = cooldown_key(wid, drop_url, matches)
            last_sent = sent.get(ck, '')
            if last_sent > cooldown_cutoff:
                log.info(f"[{wid}] Cooldown active for {drop_domain} / {matches}")
                continue

            log.info(f"[{wid}] MATCH for {email}: {matches} on {drop_domain}")

            if email not in email_alerts:
                email_alerts[email] = []
            email_alerts[email].append((watcher, matches, drop, ck))

    # Send one email per user per drop (not per watch)
    for email, alerts in email_alerts.items():
        # Take the first match — if multiple watches match same drop, send once
        seen_drops = set()
        for watcher, matches, drop, ck in alerts:
            drop_key = drop.get('url', '') + '|' + drop.get('timestamp', '')
            if drop_key in seen_drops:
                continue
            seen_drops.add(drop_key)

            subject, html, txt = build_alert_email(watcher, matches, drop)

            import alerter as _alerter
            original_to = _alerter.ALERT_TO
            _alerter.ALERT_TO = email
            result = send_email(subject, html, txt)
            _alerter.ALERT_TO = original_to

            if result:
                # Mark cooldown for ALL watchers that matched this drop
                for w2, m2, d2, ck2 in alerts:
                    if d2.get('url') == drop.get('url'):
                        sent[ck2] = now.isoformat()
                        sent_changed = True
                watcher['last_alert'] = now.isoformat()
                watcher['alert_count'] = watcher.get('alert_count', 0) + 1
                changed = True
                log.info(f"Alert sent to {email} for {drop.get('source', '')}")
            else:
                log.error(f"Failed to send to {email}")

    if changed:
        save_watchers(watchers)
    if sent_changed:
        save_sent(sent)

    log.info("Done.")


if __name__ == '__main__':
    run()
