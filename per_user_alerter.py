# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
per_user_alerter.py — Routes alerts to public watchers based on watchers.json

Runs as a cron job: */30 * * * * python3 /home/shg/drop-watcher/per_user_alerter.py

For each active watcher:
  1. Fetches their URL
  2. Checks if any of their keywords appear in the page content
  3. If match found AND not recently alerted → sends email
"""

import fcntl
import html as html_mod
import json
import os
import re
import logging
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
WATCHERS_FILE = os.path.join(BASE_DIR, 'config', 'watchers.json')
ALERT_COOLDOWN_HOURS = 6  # Don't re-alert same watcher within this window

# Reuse existing Resend email setup
from alerter import send_email

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [per_user_alerter] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; +https://instockornot.club)'
}


LOCK_FILE = WATCHERS_FILE + '.lock'

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


def fetch_page_text(url):
    from safe_fetch import is_safe_url
    safe, reason = is_safe_url(url)
    if not safe:
        log.warning(f"Blocked fetch for {url}: {reason}")
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        # Strip nav/footer/scripts
        for tag in soup(['nav', 'footer', 'script', 'style', 'header']):
            tag.decompose()
        return soup.get_text(separator=' ', strip=True).lower()
    except Exception as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None


def keywords_match(text, keywords_str):
    """Returns list of matched keywords"""
    matches = []
    # Split on comma or newline, strip whitespace
    keywords = [k.strip().lower() for k in re.split(r'[,\n]+', keywords_str) if k.strip()]
    for kw in keywords:
        if kw in text:
            matches.append(kw)
    return matches


def recently_alerted(watcher, hours=ALERT_COOLDOWN_HOURS):
    last = watcher.get('last_alert')
    if not last:
        return False
    last_dt = datetime.fromisoformat(last)
    return datetime.now(timezone.utc) - last_dt < timedelta(hours=hours)


def build_alert_email(watcher, matches, url):
    name = watcher.get('name') or 'Watcher'
    subject = f"[DROP WATCHER] Match found — {url[:60]}"

    # Escape user input for HTML context
    safe_name    = html_mod.escape(name)
    safe_url     = html_mod.escape(url)
    safe_matches = [html_mod.escape(m) for m in matches]
    unsub_token  = watcher['unsubscribe_token']

    email_html = f"""
    <div style="font-family: monospace; background: #0a0a0a; color: #e8e8e8; padding: 24px; max-width: 600px;">
      <h2 style="color: #ff2d2d; margin: 0 0 16px;">⚡ DROP WATCHER</h2>
      <p style="color: #aaa; margin: 0 0 20px; font-size: 13px;">instockornot.club</p>

      <p>Hey {safe_name} — we found a match on the page you're watching.</p>

      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Page</div>
        <a href="{safe_url}" style="color: #ff6b2b;">{safe_url}</a>
      </div>

      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Keywords matched</div>
        <div style="color: #e8e8e8;">{'  ·  '.join(safe_matches)}</div>
      </div>

      <p style="margin: 20px 0 0;">
        <a href="{safe_url}" style="background: #ff2d2d; color: white; padding: 12px 24px; text-decoration: none; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;">View Page Now →</a>
      </p>

      <hr style="border: none; border-top: 1px solid #222; margin: 32px 0;">
      <p style="color: #444; font-size: 11px;">
        <a href="https://instockornot.club/api/unsubscribe/{unsub_token}" style="color: #444;">Unsubscribe</a> · instockornot.club
      </p>
    </div>
    """

    text = f"DROP WATCHER — Match found\n\nPage: {url}\nMatched: {', '.join(matches)}\n\nView: {url}\n\nUnsubscribe: https://instockornot.club/api/unsubscribe/{unsub_token}"

    return subject, email_html, text


def run():
    watchers = load_watchers()
    active = [w for w in watchers if w.get('active', True)]
    log.info(f"Checking {len(active)} active watchers")

    changed = False

    for watcher in active:
        wid  = watcher['id']
        url  = watcher['url']
        kws  = watcher['keywords']
        email = watcher['email']

        if recently_alerted(watcher):
            log.info(f"[{wid}] Skipping — alerted recently")
            continue

        text = fetch_page_text(url)
        if not text:
            continue

        matches = keywords_match(text, kws)
        if not matches:
            log.info(f"[{wid}] No match for {email} on {url}")
            continue

        log.info(f"[{wid}] MATCH for {email}: {matches}")

        subject, html, txt = build_alert_email(watcher, matches, url)

        # Send to this watcher's email only
        # Temporarily override ALERT_TO for this send
        import alerter as _alerter
        original_to = _alerter.ALERT_TO
        _alerter.ALERT_TO = email
        result = send_email(subject, html, txt)
        _alerter.ALERT_TO = original_to

        if result:
            watcher['last_alert']  = datetime.now(timezone.utc).isoformat()
            watcher['alert_count'] = watcher.get('alert_count', 0) + 1
            changed = True
            log.info(f"[{wid}] Alert sent to {email}")
        else:
            log.error(f"[{wid}] Failed to send to {email}")

    if changed:
        save_watchers(watchers)

    log.info("Done.")


if __name__ == '__main__':
    run()
