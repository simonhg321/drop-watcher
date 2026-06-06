# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
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

import hashlib
import html as html_mod
import json
import os
import re
import logging
from datetime import datetime, timezone, timedelta

import paths
import db

COOLDOWN_HOURS = 6
DROPS_WINDOW_MINUTES = 15  # Only look at drops from last N minutes (aligns with cron)

from alerter import send_email
from matching import kw_matches
from synonyms import kw_matches_any
from urls import normalize_watch_url, domain_from_url
from makers import expand_maker
import nkd

NKD_ENABLED = os.environ.get("DW_NKD_ENABLED", "0") == "1"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [per_user_alerter] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)


def cooldown_key(watcher_id, drop_url, matches):
    """Unique key per watcher + drop URL + matched keywords."""
    match_str = ','.join(sorted(matches))
    raw = f"{watcher_id}|{drop_url}|{match_str}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_recent_drops():
    """Read drops from last DROPS_WINDOW_MINUTES minutes."""
    return db.get_recent_drops(minutes=DROPS_WINDOW_MINUTES)


# normalize_watch_url / domain_from_url now live in urls.py (single source of truth).


def keywords_match(searchable_text, keywords_str):
    """Returns list of matched keywords."""
    keywords = [k.strip().lower() for k in re.split(r'[,\n]+', keywords_str) if k.strip()]
    # kw_matches_any expands each term through its synonym group (e.g. cgg ↔ unique graphics)
    return [kw for kw in keywords if kw_matches_any(kw, searchable_text)]


def global_watch_matches(maker, keywords_str, searchable_text):
    """Global (no-URL) watch: fire iff the text names the maker (or an alias) AND at
    least one cool-list keyword. Returns the matched cool-list terms (empty = no fire)."""
    maker_terms = expand_maker(maker)
    if not maker_terms:
        return []
    if not any(kw_matches(m, searchable_text) for m in maker_terms):
        return []
    return keywords_match(searchable_text, keywords_str)


MATCHED_PRODUCTS_CAP = 8

def select_matched_products(products, matches):
    """In-stock products whose title or tags contain a matched keyword (substring).

    `products` is the structured Shopify list stored on the drop ({title, url, tags,
    available, price}); `matches` is the keywords that fired. Returns up to
    MATCHED_PRODUCTS_CAP, so an alert links straight to the items rather than the
    whole collection. Empty for non-Shopify drops (no structured products).
    """
    needles = [m.lower() for m in matches if m]
    if not needles:
        return []
    out = []
    for p in products:
        if not p.get('available') or not p.get('url'):
            continue
        hay = (p.get('title', '') + ' ' + ' '.join(p.get('tags') or [])).lower()
        if any(kw_matches(n, hay) for n in needles):
            out.append(p)
        if len(out) >= MATCHED_PRODUCTS_CAP:
            break
    return out


def build_alert_email(watcher, matches, drop):
    name = watcher.get('name') or 'Watcher'
    url = drop.get('url', '')
    subject = f"[DROP WATCHER] Match found — {drop.get('source', url[:40])}"

    safe_name    = html_mod.escape(name)
    safe_url     = html_mod.escape(url)
    safe_matches = [html_mod.escape(m) for m in matches]
    unsub_token  = watcher['unsubscribe_token']
    # `or` (not a .get default) — the AI can emit JSON null for these keys, so the key
    # is present with value None and a plain default never applies (S49 null-class bug).
    summary      = html_mod.escape(drop.get('page_summary') or '')
    notable      = drop.get('notable_items') or []
    safe_notable = [html_mod.escape(n) for n in notable[:5]]

    # Deep-link to the specific in-stock products that matched the keyword(s).
    # Only Shopify drops carry a structured product list (drop['products']); for
    # everything else this stays empty and the email falls back to the page link.
    matched_products = select_matched_products(drop.get('products') or [], matches)

    nkd_html = ''
    nkd_text_line = ''
    if NKD_ENABLED:
        nkd_token = nkd.make_token(watcher['id'], url)
        nkd_url = f"https://instockornot.club/nkd.html?t={nkd_token}"
        nkd_html = f'''
      <p style="margin: 16px 0 0;">
        <a href="{nkd_url}" style="background: #27ae60; color: white; padding: 10px 20px; text-decoration: none; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;">🔪 I Scored One →</a>
      </p>'''
        nkd_text_line = f"\nDid you score one? Tell us: {nkd_url}\n"

    notable_html = ''
    if safe_notable:
        items = ''.join(f'<li style="color:#e8e8e8;margin:4px 0">{n}</li>' for n in safe_notable)
        notable_html = f'''
      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Notable items</div>
        <ul style="margin:0;padding-left:20px">{items}</ul>
      </div>'''

    # Matched items — direct deep-links to the in-stock products that matched.
    matched_html = ''
    if matched_products:
        rows = ''
        for p in matched_products:
            p_url   = html_mod.escape(p.get('url', ''))
            p_title = html_mod.escape(p.get('title', '') or p.get('url', ''))
            price   = p.get('price', '')
            price_s = f' <span style="color:#666">— ${html_mod.escape(str(price))}</span>' if price else ''
            rows += (f'<li style="margin:6px 0">'
                     f'<a href="{p_url}" style="color:#ff6b2b;text-decoration:none">{p_title}</a>'
                     f'{price_s}</li>')
        matched_html = f'''
      <div style="background: #161616; border: 1px solid #2a1a0a; padding: 16px; margin: 20px 0;">
        <div style="color: #ff6b2b; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Matched items — in stock now</div>
        <ul style="margin:0;padding-left:20px;list-style:none">{rows}</ul>
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

      {matched_html}

      {notable_html}

      <p style="margin: 20px 0 0;">
        <a href="{safe_url}" style="background: #ff2d2d; color: white; padding: 12px 24px; text-decoration: none; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;">View Page Now →</a>
      </p>

      <p style="margin: 16px 0 0;">
        <a href="https://instockornot.club/my-alerts.html?token={unsub_token}" style="background: #e67e22; color: white; padding: 10px 20px; text-decoration: none; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;">My Alerts Dashboard</a>
      </p>
      {nkd_html}

      <hr style="border: none; border-top: 1px solid #222; margin: 32px 0;">
      <p style="color: #888; font-size: 12px;">
        Still want these alerts?
        <a href="https://instockornot.club/api/ack/{unsub_token}" style="color: #27ae60; text-decoration: underline;">Keep this watch alive →</a>
      </p>
      <p style="color: #444; font-size: 11px;">
        <a href="https://instockornot.club/api/unsubscribe/{unsub_token}" style="color: #444;">Unsubscribe</a> · instockornot.club
      </p>
    </div>
    """

    matched_text = ''
    if matched_products:
        lines = '\n'.join(
            f"  - {p.get('title', '') or p.get('url', '')}"
            f"{(' — $' + str(p.get('price'))) if p.get('price') else ''}\n    {p.get('url', '')}"
            for p in matched_products
        )
        matched_text = f"Matched items (in stock now):\n{lines}\n\n"

    text = (
        f"DROP WATCHER — Match found\n\n"
        f"Source: {drop.get('source', '')}\n"
        f"Page: {url}\n"
        f"Matched: {', '.join(matches)}\n"
        f"Summary: {drop.get('page_summary') or ''}\n\n"
        f"{matched_text}"
        f"View: {url}\n\n"
        f"Dashboard: https://instockornot.club/my-alerts.html?token={unsub_token}\n"
        f"{nkd_text_line}"
        f"Keep this watch alive: https://instockornot.club/api/ack/{unsub_token}\n"
        f"Unsubscribe: https://instockornot.club/api/unsubscribe/{unsub_token}"
    )

    return subject, email_html, text


def run():
    active = db.get_active_watchers()
    log.info(f"Checking {len(active)} active watchers against recent drops")

    if not active:
        log.info("No active watchers. Done.")
        return

    drops = load_recent_drops()
    log.info(f"Found {len(drops)} drops in last {DROPS_WINDOW_MINUTES} minutes")

    if not drops:
        log.info("No recent drops. Done.")
        return

    now = datetime.now(timezone.utc)

    # Group watchers by email to avoid duplicate emails
    email_alerts = {}  # email -> list of (watcher, matches, drop)

    for watcher in active:
        wid   = watcher['id']
        w_url = watcher.get('url', '').lower()
        kws   = watcher.get('keywords', '')
        email = watcher['email']
        maker = watcher.get('maker', '')

        is_global = not w_url
        for drop in drops:
            drop_url    = (drop.get('url') or '').lower()
            drop_domain = domain_from_url(drop_url)
            is_user_drop = (drop.get('source') or '').endswith('(user)')

            # Build searchable text from the real page content (excerpt + the AI's
            # detected keyword hits), not just its prose summary — so literal keywords
            # like "damascus" or "add to cart" match what's actually on the page.
            summary   = (drop.get('page_summary') or '').lower()
            notable   = ' '.join(drop.get('notable_items') or []).lower()
            kw_found  = ' '.join(drop.get('keywords_found') or []).lower()
            excerpt   = (drop.get('page_excerpt') or '').lower()
            searchable = f"{summary} {notable} {kw_found} {excerpt}"

            if is_global:
                # Global watch: match maker+cool-list against EVERY curated drop.
                # Skip user-watch drops (those belong to their exact-URL owner).
                if is_user_drop:
                    continue
                matches = global_watch_matches(maker, kws, searchable)
                if not matches:
                    continue
            else:
                # w_domain/w_norm are only needed for the non-global (URL-scoped) path.
                w_domain = domain_from_url(w_url)
                w_norm   = normalize_watch_url(w_url)
                # Match scope: a user-watch drop is produced from ONE specific page, so it
                # may only match the watcher of that exact URL — otherwise two watches on
                # the same domain (different paths/keywords) cross-contaminate now that the
                # searchable text includes the full page excerpt. Curated/feed drops still
                # fan out to every watcher on the domain.
                if is_user_drop:
                    if not w_norm or w_norm != normalize_watch_url(drop_url):
                        continue
                elif not w_domain or w_domain != drop_domain:
                    continue
                matches = keywords_match(searchable, kws)
                if not matches:
                    continue

            # Check per-URL-per-keyword cooldown
            ck = cooldown_key(wid, drop_url, matches)
            if db.is_cooldown_active(ck, hours=COOLDOWN_HOURS):
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
            # Dedup the SAME drop matching multiple of this user's watches. Fold in
            # source + an items hash so two genuinely different drops at the same URL
            # (e.g. a timestamp-less feed restock) don't collapse into one.
            drop_key = '|'.join([
                drop.get('url', ''),
                drop.get('timestamp', ''),
                drop.get('source', ''),
                hashlib.md5(str(drop.get('notable_items', '')).encode()).hexdigest()[:8],
            ])
            if drop_key in seen_drops:
                continue
            seen_drops.add(drop_key)

            try:
                subject, html, txt = build_alert_email(watcher, matches, drop)

                result = send_email(subject, html, txt, to_addr=email)
            except Exception as e:
                # One malformed watcher row must not abort the remaining users'
                # alerts for this run (they'd age out of the recent-drops window).
                log.error(f"Alert build/send failed for {email} (watcher {watcher.get('id')}): {e}")
                continue

            if result:
                # Mark cooldown for THIS watcher's match only
                db.mark_cooldown(ck, recipient=email)
                db.update_watcher(watcher['id'],
                    last_alert=now.isoformat(),
                    alert_count=watcher.get('alert_count', 0) + 1)
                log.info(f"Alert sent to {email} for {drop.get('source', '')}")

                # SMS fan-out — only sms_approved watchers, only high/critical priority.
                # Per-URL-per-keyword cooldown above already prevents spam.
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
                        if _send_twilio_sms(phone, body):
                            log.info(f"SMS sent to {phone} for {email}")
                        else:
                            log.error(f"SMS failed to {phone} for {email}")
                    except Exception as e:
                        log.error(f"SMS fan-out exception for {email}: {e}")
            else:
                log.error(f"Failed to send to {email}")

    log.info("Done.")


if __name__ == '__main__':
    run()
