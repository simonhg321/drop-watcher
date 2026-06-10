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
import linkpick
import nkd

NKD_ENABLED = os.environ.get("DW_NKD_ENABLED", "0") == "1"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [per_user_alerter] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)


def is_low_confidence(item):
    """True when an alert item is a best-effort (tier-3 DOM / fuzzy) link, not a
    structured-feed deep-link — rendered with a 🤔 so users double-check it."""
    return (item.get('confidence') or 'high') == 'low'


def alert_is_uncertain(matched_items):
    """True when an alert isn't backed by a confident structured deep-link: either a
    matched item is low-confidence (tier-3/fuzzy), or nothing resolved to a specific
    item (notable/page fallback). Such alerts get the keyword-improvement prompt."""
    return (not matched_items) or any(is_low_confidence(it) for it in matched_items)


def keyword_hint_html(unsub_token):
    return (
        '<div style="color:#999;font-size:12px;line-height:1.5;margin-top:10px">'
        '🤔 We believe your keywords match this page — but we\'re not 100% sure. '
        'Better keywords mean better matches. '
        f'<a href="https://instockornot.club/my-alerts.html?token={unsub_token}" '
        'style="color:#ff8c42">Refine your keywords →</a></div>'
    )


KEYWORD_HINT_TEXT = (
    "\n🤔 We believe your keywords match this page — but we're not 100% sure.\n"
    "Better keywords mean better matches. Refine yours: "
    "https://instockornot.club/my-alerts.html?token={token}\n"
)


def mismatch_banner_html():
    """Small banner shown on uncertain alerts: the deep-link may not land on the exact
    product. Tell the user to try it, and if it's off, search the site themselves."""
    return (
        '<div style="background:#2a1a0a;border:1px solid #ff8c42;border-radius:4px;'
        'padding:12px 14px;margin:16px 0;color:#ffd6b0;font-size:12px;line-height:1.5">'
        '⚠️ <strong>This link may not land on the exact product.</strong> '
        'Try it — and if it doesn\'t match, search the site for your grail; it may '
        'still be in stock. We\'re working on a fix.'
        '</div>'
    )


MISMATCH_BANNER_TEXT = (
    "\n⚠️ This link may not land on the exact product. Try it — and if it doesn't\n"
    "match, search the site for your grail; it may still be in stock. We're working on a fix.\n"
)


def cooldown_key(watcher_id, drop_url, matches):
    """Cooldown scoped to watcher + domain + matched keywords.
    Domain-level (not URL-level) so the same restock seen by web_watcher
    AND feed_watcher doesn't fire twice."""
    match_str = ','.join(sorted(matches))
    domain = domain_from_url(drop_url) or drop_url
    raw = f"{watcher_id}|{domain}|{match_str}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_recent_drops():
    """Read drops from last DROPS_WINDOW_MINUTES minutes."""
    return db.get_recent_drops(minutes=DROPS_WINDOW_MINUTES)


def load_unprocessed_drops():
    """All drops since last successful run. Never misses a drop."""
    return db.get_unprocessed_drops(consumer='per_user_alerter')


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


def disclaimer_html():
    """Early-days disclaimer + feedback ask, shared by every results email (live
    alert + signup backfill) so the message stays consistent."""
    return (
        '<p style="color:#e8e8e8;font-size:12px;line-height:1.6;margin-top:24px;'
        'border-top:1px solid #222;padding-top:16px">'
        'These results are brand new and instockornot.club is still being refined — '
        'we expect matches to get sharper the more Drop Watcher is used, and '
        '<strong>the better your keywords, the better the results</strong>. '
        'We\'re grateful to our new users. Got feedback? We\'d love it: '
        '<a href="mailto:info@instockornot.club" style="color:#ff8c42">info@instockornot.club</a>'
        '</p>'
    )


DISCLAIMER_TEXT = (
    "\n--\n"
    "These results are brand new and instockornot.club is still being refined — we expect\n"
    "matches to get sharper the more Drop Watcher is used, and the better your keywords, the\n"
    "better the results. We're grateful to our new users.\n"
    "Got feedback? We'd love it: info@instockornot.club\n"
)


def drop_searchable_text(drop):
    """Lowercased blob of a drop's real page content used for keyword matching:
    prose summary + notable items + the AI's detected keyword hits + page excerpt.
    Single source of truth so the live alerter and the signup backfill search the
    exact same text."""
    summary  = (drop.get('page_summary') or '').lower()
    notable  = ' '.join(drop.get('notable_items') or []).lower()
    kw_found = ' '.join(drop.get('keywords_found') or []).lower()
    excerpt  = (drop.get('page_excerpt') or '').lower()
    return f"{summary} {notable} {kw_found} {excerpt}"


def matches_for_watcher_drop(watcher, drop):
    """Matched keywords for ONE watcher against ONE drop, or [] if no match.

    Pure: no cooldown, no I/O. This is the single matching decision shared by the
    live windowed alerter (run) and the signup backfill (backfill_alerter), so the
    two can never diverge on what counts as a match. Encapsulates the
    global-vs-URL-scoped branch and user-drop scoping.
    """
    w_url = (watcher.get('url') or '').lower()
    kws   = watcher.get('keywords', '')
    maker = watcher.get('maker', '')
    is_global = not w_url

    drop_url     = (drop.get('url') or '').lower()
    is_user_drop = (drop.get('source') or '').endswith('(user)')
    searchable   = drop_searchable_text(drop)

    if is_global:
        # Global watch: match maker+cool-list against EVERY curated drop.
        # Skip user-watch drops (those belong to their exact-URL owner).
        if is_user_drop:
            return []
        return global_watch_matches(maker, kws, searchable)

    # URL-scoped watch. A user-watch drop is produced from ONE specific page, so it
    # may only match the watcher of that exact URL — otherwise two watches on the
    # same domain cross-contaminate now that searchable includes the full excerpt.
    # Curated/feed drops still fan out to every watcher on the domain.
    w_domain = domain_from_url(w_url)
    w_norm   = normalize_watch_url(w_url)
    if is_user_drop:
        if not w_norm or w_norm != normalize_watch_url(drop_url):
            return []
    elif not w_domain or w_domain != domain_from_url(drop_url):
        return []
    return keywords_match(searchable, kws)


MATCHED_PRODUCTS_CAP = 8

def select_matched_products(products, matches):
    """In-stock products whose title or tags contain a matched keyword (substring).

    `products` is the structured product list stored on the drop ({title, url, tags,
    available, price}), sourced from Shopify products.json, JSON-LD, or product-card
    extraction; `matches` is the keywords that fired. Returns up to MATCHED_PRODUCTS_CAP,
    so an alert links straight to the items rather than the whole collection. Returns []
    when the drop has no structured products.
    """
    needles = [m.lower() for m in matches if m]
    if not needles:
        return []
    # Verify availability BEFORE counting toward the cap — capping first could
    # discard a live match because sold-out ones used up the slots.
    from backfill_alerter import _is_still_available
    verified = []
    for p in products:
        if not p.get('available') or not p.get('url'):
            continue
        hay = (p.get('title', '') + ' ' + ' '.join(p.get('tags') or [])).lower()
        if not any(kw_matches(n, hay) for n in needles):
            continue
        if _is_still_available(p.get('url', '')) is False:
            log.info(f"  Dropped sold-out product: {p.get('title', '')[:60]}")
            continue
        verified.append(p)
        if len(verified) >= MATCHED_PRODUCTS_CAP:
            break
    return verified


_PRICE_RE = re.compile(r'\$[\d,]+(?:\.\d{2})?')

# User-watch notable_items carry a status label and MAY include sold-out items (the
# analyze_user_page prompt asks the AI to list them with status). We must never
# deep-link those — a sold-out item lands on a dead/unbuyable page. Curated drops are
# already in-stock-only, so this only ever fires on user watches.
_SOLD_OUT_RE = re.compile(r'(sold[\s-]?out|out[\s-]?of[\s-]?stock|notify\s*me|unavailable|\boos\b)', re.I)


def _is_sold_out(text):
    """True if an item label signals it's not purchasable. 'in stock' never matches."""
    return bool(_SOLD_OUT_RE.search(text or ''))


def _split_title_price(text):
    """Notable-item lines read like 'Maker Model Steel - $312.00 (in stock)'. Pull the
    price out and trim the title to the part before the price tail."""
    m = _PRICE_RE.search(text)
    price = m.group(0).lstrip('$') if m else ''
    title = text
    if m:
        idx = text.rfind(' - ', 0, m.start())
        title = text[:idx] if idx != -1 else text[:m.start()]
    return title.strip(' -–—'), price


def item_page_link(drop):
    """Most specific URL we can stand behind for a drop's item when no per-item URL
    resolves: Reddit posts / feed entries ARE the listing; else the scraped page.
    Never a fabricated /search (store search paths vary and 404)."""
    return drop.get('entry_url') or drop.get('url') or ''


def resolve_drop_items(drop, matches):
    """Specific matched items for a drop, each {title, url, price}, deep-linked to the
    actual product where possible. Single source of truth for both the live alert
    email and the signup backfill digest. Returns [] when nothing item-level resolves
    (caller decides whether to fall back to the page).

    Priority:
      1. structured products → canonical product URL
      2. matched notable-item lines → deep-link via linkpick candidate resolution
         (resolve by the product NAME, not the keyword — avoids the wrong-product bug)
      3. keyword matched only the page excerpt → resolve one best candidate for the terms
    """
    prods = select_matched_products(drop.get('products') or [], matches)
    if prods:
        return [{'title': p.get('title') or p.get('url'),
                 'url': p.get('url'),
                 'price': p.get('price', ''),
                 'confidence': p.get('confidence', 'high')} for p in prods]

    candidates = drop.get('link_candidates') or []
    link = item_page_link(drop)
    items = []
    needles = [m.lower() for m in matches if m]
    for n in (drop.get('notable_items') or []):
        if any(kw_matches(k, n.lower()) for k in needles):
            if _is_sold_out(n):
                continue   # never deep-link a sold-out item to a dead page
            title, price = _split_title_price(n)
            c = linkpick.best_candidate(candidates, linkpick.strip_status_prefix(title or n))
            items.append({'title': title or n, 'url': (c['href'] if c else link), 'price': price,
                          'confidence': 'low'})
        if len(items) >= MATCHED_PRODUCTS_CAP:
            break
    if items:
        return items

    # Try notable_items_detail — Haiku may have extracted URLs there even when
    # the item didn't land in notable_items (or the keyword matched only the excerpt).
    for d in (drop.get('notable_items_detail') or []):
        dname = (d.get('name') or '').lower()
        if any(kw_matches(k, dname) for k in needles):
            # These URLs are Haiku-supplied: absolutise EVERY form (bare-relative,
            # protocol-relative, absolute) then require http(s) + same-site, like
            # every other tier — never emit a dead or cross-site href.
            from urllib.parse import urljoin, urlparse
            base = drop.get('url') or ''
            url = urljoin(base, d.get('url') or '')
            pu = urlparse(url)
            if (pu.scheme not in ('http', 'https')
                    or not linkpick.same_site(pu.hostname, urlparse(base).hostname)):
                url = ''
            if url:
                items.append({'title': d.get('name', ''), 'url': url,
                              'price': d.get('price', ''), 'confidence': 'low'})
            if len(items) >= MATCHED_PRODUCTS_CAP:
                break
    if items:
        return items

    c = linkpick.resolve_alert_candidate(
        candidates, notable_items=drop.get('notable_items'), keywords=matches)
    if c:
        title = linkpick.clean_title(c['text']) or linkpick.title_from_slug(c['href']) or drop.get('source', '')
        return [{'title': title, 'url': c['href'], 'price': '', 'confidence': 'low'}]

    # Last resort: /collections/all on the site ORIGIN — but only when the drop
    # is Shopify-shaped (some product URL contains /products/). Anything else
    # (Reddit, feeds, query-string watch URLs) would 404 — return [] honestly,
    # same rule as item_page_link's "never a fabricated /search".
    base = drop.get('url') or ''
    shopify_shaped = any(
        '/products/' in u for u in (
            [(c.get('href') or '') if isinstance(c, dict) else '' for c in candidates]
            + [(d.get('url') or '') for d in (drop.get('notable_items_detail') or [])]
        ) if u)
    if base and shopify_shaped:
        from urllib.parse import urlsplit
        sp = urlsplit(base)
        if sp.scheme in ('http', 'https') and sp.netloc:
            fallback = f"{sp.scheme}://{sp.netloc}/collections/all"
            kw_label = ', '.join(matches[:3])
            return [{'title': kw_label, 'url': fallback, 'price': '', 'confidence': 'low'}]
    return []


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

    # Deep-link to the specific in-stock items that matched. Shopify drops resolve via
    # their structured product list; non-Shopify store drops resolve via scraped link
    # candidates; Reddit/feed via the post URL. Empty → fall back to plain notable text.
    matched_items = resolve_drop_items(drop, matches)

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

    # Matched items — deep-links to the specific in-stock items that matched. When
    # nothing item-level resolves, fall back to the plain "Notable items" context list.
    matched_html = ''
    notable_html = ''
    if matched_items:
        rows = ''
        for it in matched_items:
            p_url   = html_mod.escape(it.get('url', ''))
            p_title = html_mod.escape(it.get('title', '') or it.get('url', ''))
            price   = it.get('price', '')
            price_s = f' <span style="color:#666">— ${html_mod.escape(str(price))}</span>' if price else ''
            low_badge = (' <span title="best-effort extracted link — double-check on the page"'
                         ' style="cursor:help">🤔</span>') if is_low_confidence(it) else ''
            rows += (f'<li style="margin:6px 0">'
                     f'<a href="{p_url}" style="color:#ff6b2b;text-decoration:none">{p_title}</a>'
                     f'{low_badge}{price_s}</li>')
        matched_html = f'''
      <div style="background: #161616; border: 1px solid #2a1a0a; padding: 16px; margin: 20px 0;">
        <div style="color: #ff6b2b; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Matched items — in stock now</div>
        <ul style="margin:0;padding-left:20px;list-style:none">{rows}</ul>
      </div>'''
    elif safe_notable:
        items = ''.join(f'<li style="color:#e8e8e8;margin:4px 0">{n}</li>' for n in safe_notable)
        notable_html = f'''
      <div style="background: #161616; border: 1px solid #222; padding: 16px; margin: 20px 0;">
        <div style="color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">Notable items</div>
        <ul style="margin:0;padding-left:20px">{items}</ul>
      </div>'''

    show_hint = alert_is_uncertain(matched_items)
    keyword_hint = keyword_hint_html(unsub_token) if show_hint else ''
    mismatch_banner = mismatch_banner_html() if show_hint else ''

    email_html = f"""
    <div style="font-family: monospace; background: #0a0a0a; color: #e8e8e8; padding: 24px; max-width: 600px;">
      <h2 style="color: #ff2d2d; margin: 0 0 16px;">⚡ DROP WATCHER</h2>
      <p style="color: #aaa; margin: 0 0 20px; font-size: 13px;">instockornot.club</p>

      <p>Hey {safe_name} — we found a match on a page you're watching.</p>

      {mismatch_banner}

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

      {keyword_hint}

      <p style="margin: 20px 0 0;">
        <a href="{safe_url}" style="background: #ff2d2d; color: white; padding: 12px 24px; text-decoration: none; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;">View Page Now →</a>
      </p>

      <p style="margin: 16px 0 0;">
        <a href="https://instockornot.club/my-alerts.html?token={unsub_token}" style="background: #e67e22; color: white; padding: 10px 20px; text-decoration: none; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;">My Alerts Dashboard</a>
      </p>
      {nkd_html}

      {disclaimer_html()}

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
    if matched_items:
        lines = '\n'.join(
            f"  - {it.get('title', '') or it.get('url', '')}"
            f"{(' — $' + str(it.get('price'))) if it.get('price') else ''}"
            f"{' 🤔 (best-effort link)' if is_low_confidence(it) else ''}"
            f"\n    {it.get('url', '')}"
            for it in matched_items
        )
        matched_text = f"Matched items (in stock now):\n{lines}\n\n"

    hint_text = KEYWORD_HINT_TEXT.format(token=unsub_token) if show_hint else ''
    banner_text = MISMATCH_BANNER_TEXT if show_hint else ''

    text = (
        f"DROP WATCHER — Match found\n"
        f"{banner_text}\n"
        f"Source: {drop.get('source', '')}\n"
        f"Page: {url}\n"
        f"Matched: {', '.join(matches)}\n"
        f"Summary: {drop.get('page_summary') or ''}\n\n"
        f"{matched_text}"
        f"{hint_text}"
        f"View: {url}\n\n"
        f"Dashboard: https://instockornot.club/my-alerts.html?token={unsub_token}\n"
        f"{nkd_text_line}"
        f"{DISCLAIMER_TEXT}"
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

    drop_rows = load_unprocessed_drops()
    log.info(f"Found {len(drop_rows)} unprocessed drops")

    if not drop_rows:
        log.info("No unprocessed drops. Done.")
        return

    drops = [d for _, d in drop_rows]
    max_id = max(did for did, _ in drop_rows)

    now = datetime.now(timezone.utc)

    # Group watchers by email to avoid duplicate emails
    email_alerts = {}  # email -> list of (watcher, matches, drop)

    for watcher in active:
        wid   = watcher['id']
        email = watcher['email']

        for drop in drops:
            drop_url    = (drop.get('url') or '').lower()
            drop_domain = domain_from_url(drop_url)

            matches = matches_for_watcher_drop(watcher, drop)
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

    db.set_hwm('per_user_alerter', max_id)
    log.info(f"HWM advanced to {max_id}")
    log.info("Done.")


if __name__ == '__main__':
    run()
