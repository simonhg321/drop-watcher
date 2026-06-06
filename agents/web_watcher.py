# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
web_watcher.py
Drop Watcher — Web Agent
Monitors two classes of URLs:
  1. Curated sources (sources.yaml) — knife/EDC market, AI analyzed with maker priority rules
  2. User-submitted watches (watchers.json) — any URL, any product, AI analyzed for stock status
SSL permissive support + AI interpretation layer.
HGR
"""

import os
import sys
import ssl
import json
import time
import random
import logging
import hashlib
from datetime import datetime, timezone

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Load environment ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import paths
import db
load_dotenv(paths.ENV_FILE)

# ── Add agents dir to path so we can import ai_interpreter ───────────────────
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))
from ai_interpreter import analyze_page, analyze_user_page
import collection_fetch
from safe_fetch import is_safe_url
from urls import normalize_watch_url, domain_from_url
from config_load import load_yaml, build_keywords, prefilter
from urllib.parse import urljoin

# ── Paths ─────────────────────────────────────────────────────────────────────
CONFIG_DIR = paths.CONFIG_DIR
LOG_DIR    = paths.LOG_DIR

SOURCES_FILE   = paths.SOURCES_YAML
COOL_LIST_FILE = paths.COOL_LIST_YAML
MAKERS_FILE    = paths.MAKERS_YAML
SETTINGS_FILE  = paths.SETTINGS_YAML

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'web_watcher.log')),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('web_watcher')

# ── YAML loader ───────────────────────────────────────────────────────────────
# load_yaml / build_keywords / prefilter now live in config_load.py (shared with
# feed_watcher so the two scrapers pre-filter identically). build_makers_list is local.

# ── Build makers list for AI ──────────────────────────────────────────────────
def build_makers_list(makers_config):
    return [maker['name'] for maker in makers_config.get('makers', [])]

# ── Page fingerprint ──────────────────────────────────────────────────────────
def fingerprint(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def page_fingerprint(text, products):
    """Change-detection fingerprint over a NORMALIZED projection of the page.

    Raw-text fingerprints flip on cosmetic churn (cart counts, CSRF tokens,
    'N people viewing') and bust the cache, triggering a paid AI call when nothing
    meaningful changed. For Shopify pages the meaningful state is the set of
    (title, in-stock?) tuples; non-structured pages fall back to raw text. (S51 P3b)
    """
    if products:
        proj = sorted((str(p.get('title', '')), bool(p.get('available'))) for p in products)
        return hashlib.md5(repr(proj).encode('utf-8')).hexdigest()
    return fingerprint(text)

# ── Structured products for deep-linking matched items ────────────────────────
PRODUCTS_STORE_CAP = 80

def instock_products(products):
    """Trim a Shopify product list to in-stock items for deep-linking in alerts.

    Only in-stock items are alert-worthy, and capping keeps the JSON we stash on the
    drop (drops.raw_json) bounded even for 750-product catalogs. Returns [] for
    non-Shopify pages (products is None) — alerter then falls back to the page link.
    """
    if not products:
        return []
    return [
        {
            'title': p.get('title', ''),
            'url': p.get('url', ''),
            'tags': p.get('tags', []),
            'price': p.get('price', ''),
            'available': True,
        }
        for p in products if p.get('available')
    ][:PRODUCTS_STORE_CAP]

# prefilter moved to config_load.py (imported below).


# ── Homepage / nav-only detection ─────────────────────────────────────────────
HOMEPAGE_SIGNALS = [
    'skip to content', 'skip to main', 'cookie policy', 'accept cookies',
    'subscribe to newsletter', 'sign up for', 'free shipping over',
    'shop all', 'all products', 'all categories', 'browse categories',
]

def is_homepage_junk(text):
    """Detect if stripped page content is mostly navigation/menu with no real product data."""
    text_lower = text.lower()
    # Count homepage signals
    signals = sum(1 for s in HOMEPAGE_SIGNALS if s in text_lower)
    # Short pages with lots of nav signals = homepage
    words = len(text.split())
    if words < 200 and signals >= 2:
        return True
    # High signal-to-content ratio
    if words < 500 and signals >= 3:
        return True
    return False


# ── Stale user watch throttling ───────────────────────────────────────────────
# Track consecutive "not found" results per URL — throttle after threshold
stale_watch_count = {}  # url → consecutive not-found count
STALE_THRESHOLD = 3     # after 3 identical "not found", slow down
STALE_INTERVAL = 3600   # throttle to hourly (seconds)


# ── Item deduplication (via SQLite) ───────────────────────────────────────────
CONTENT_DEDUP_HOURS = 4
DEDUP_HOURS = 24

def content_key(source, summary):
    return f"{source}:{hashlib.md5((summary or '').encode()).hexdigest()[:8]}"

def is_content_seen(source, summary, _unused=None):
    key = content_key(source, summary)
    return db.is_content_seen(key, hours=CONTENT_DEDUP_HOURS)

def mark_content_seen(source, summary, _unused=None):
    key = content_key(source, summary)
    db.mark_content_seen(key)
    return _unused  # kept for API compat

def item_key(source, item):
    raw = f"{source}:{item[:80].lower()}"
    return hashlib.md5(raw.encode()).hexdigest()

def filter_new_items(source, notable_items, _unused=None):
    new_items = []
    for item in (notable_items or []):
        if not item:
            continue
        key = item_key(source, str(item))
        if not db.is_item_seen(key, hours=DEDUP_HOURS):
            new_items.append(item)
    return new_items

def mark_items_seen(source, notable_items, _unused=None):
    for item in (notable_items or []):
        if not item:
            continue
        key = item_key(source, str(item))
        db.mark_item_seen(key)
    return _unused

# ── Alert writer ──────────────────────────────────────────────────────────────
def write_alert(settings, alert):
    db.add_drop(alert)

    log.info(f"ALERT: {alert['source']}")
    if alert.get('notable_items'):
        for item in alert['notable_items']:
            log.info(f"   -> {item}")
    if alert.get('drop_announcement', {}).get('detected'):
        drop = alert['drop_announcement']
        log.info(f"   DROP: {drop.get('maker')} -- {drop.get('description')} -- {drop.get('timing')}")

# ── Permissive SSL adapter ────────────────────────────────────────────────────
class PermissiveSSLAdapter(HTTPAdapter):
    """
    For sites with non-standard or misconfigured TLS.
    Only used when ssl_permissive: true in sources.yaml.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ── Fetch ─────────────────────────────────────────────────────────────────────
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; personal use)'
}

MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB — reject oversized pages
MAX_REDIRECTS = 4

def fetch_page(url, ssl_permissive=False):
    # SSRF guard: this fetches user-submitted watch URLs every cycle, so an attacker
    # could otherwise store http://169.254.169.254/ or http://127.0.0.1:5001/ and have
    # the scraper hit it server-side. Validate the URL AND every redirect hop (curated
    # dealers legitimately redirect http->https / www->apex, so we follow but re-check).
    safe, reason = is_safe_url(url)
    if not safe:
        log.warning(f"Refusing to fetch unsafe URL {url}: {reason}")
        return None
    try:
        session = requests.Session()
        if ssl_permissive:
            session.mount('https://', PermissiveSSLAdapter())
            log.debug(f"Using permissive SSL for {url}")
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            response = session.get(
                current,
                headers=HEADERS,
                timeout=15,
                verify=not ssl_permissive,
                stream=True,
                allow_redirects=False,
            )
            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                loc = response.headers.get('Location', '')
                response.close()
                if not loc:
                    return None
                current = urljoin(current, loc)
                safe, reason = is_safe_url(current)
                if not safe:
                    log.warning(f"Refusing redirect to unsafe URL {current}: {reason}")
                    return None
                continue
            response.raise_for_status()
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                log.warning(f"Skipping {current} — Content-Length {content_length} exceeds 2MB limit")
                response.close()
                return None
            content = response.content[:MAX_RESPONSE_BYTES]
            response.close()
            return content.decode('utf-8', errors='replace')
        log.warning(f"Too many redirects for {url}")
        return None
    except requests.RequestException as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None

# ── User-submitted watch URLs ─────────────────────────────────────────────────
USER_POLL_INTERVAL = 15 * 60          # scrape user URLs every 15 min
USER_SITES_RELOAD_INTERVAL = 5 * 60   # reload watchers.json every 5 min

# normalize_watch_url / domain_from_url now live in urls.py (single source of truth
# shared with per_user_alerter + watcher_signup so matching can't silently diverge).

def load_user_sites(source_urls):
    """Load unique URLs from active watchers that aren't already curated sources.

    Dedup is by EXACT normalized URL, not domain. A deeper path on a domain we also
    curate (e.g. knifejoy.com/collections/chris-reeve-knives when knifejoy.com is a
    curated source) is a distinct user watch and MUST still be polled — domain-level
    dedup silently dropped these and the user's watch never fired.
    """
    try:
        watchers = db.get_active_watchers()
    except Exception as e:
        log.warning(f"Could not load watchers for user sites: {e}")
        return {}

    user_sites = {}  # url -> {url, keywords: set, name}
    for w in watchers:
        url = w.get('url', '').strip()
        if not url:
            continue
        if normalize_watch_url(url) in source_urls:
            continue
        domain = domain_from_url(url)
        if url not in user_sites:
            user_sites[url] = {'url': url, 'keywords': set(), 'name': domain}
        kws = [k.strip().lower() for k in w.get('keywords', '').split(',') if k.strip()]
        user_sites[url]['keywords'].update(kws)

    for site in user_sites.values():
        site['keywords'] = list(site['keywords'])
    return user_sites

# ── Main loop ─────────────────────────────────────────────────────────────────
def run():
    log.info("Web Watcher starting up — HGR")

    sources  = load_yaml(SOURCES_FILE)
    cool     = load_yaml(COOL_LIST_FILE)
    makers   = load_yaml(MAKERS_FILE)
    settings = load_yaml(SETTINGS_FILE)

    keywords    = build_keywords(cool, makers)
    makers_list = build_makers_list(makers)
    jitter      = settings['polling']['jitter_seconds']
    min_gap     = settings['polling']['min_domain_gap_seconds']
    fail_thresh = settings['agent']['failure_threshold']
    retry_delay = settings['agent']['retry_delay_seconds']

    log.info(f"Loaded {len(keywords)} keywords for pre-filter")
    log.info(f"Loaded {len(makers_list)} makers for AI analysis")
    log.info(f"Loaded {len(sources.get('websites', []))} websites")

    page_cache    = {}
    failure_count = {}

    websites = [s for s in sources.get('websites', []) if s.get('enabled', True)]

    # Build set of curated source URLs (exact-URL match, not domain) so a user's
    # deep-link watch on a domain we also curate is still polled as its own watch.
    source_urls = set()
    for site in websites:
        source_urls.add(normalize_watch_url(site['url']))

    user_sites = {}
    last_user_reload = 0

    while True:
        for site in websites:
            name           = site['name']
            url            = site['url']
            interval       = site.get('poll_interval', 20) * 60
            ssl_permissive = site.get('ssl_permissive', False)

            last_checked = page_cache.get(url, {}).get('last_checked', 0)
            if time.time() - last_checked < interval:
                continue

            sleep_time = random.randint(min_gap, min_gap + jitter)
            log.info(f"Checking {name} in {sleep_time}s...")
            time.sleep(sleep_time)

            text, products = collection_fetch.fetch_collection(
                url, fetch_page, ssl_permissive=ssl_permissive, log=log)
            if text is None:
                failure_count[url] = failure_count.get(url, 0) + 1
                if failure_count[url] >= fail_thresh:
                    log.error(f"{name} has failed {failure_count[url]} times in a row")
                time.sleep(retry_delay)
                continue

            failure_count[url] = 0

            fp     = page_fingerprint(text, products)
            old_fp = page_cache.get(url, {}).get('fingerprint')

            page_cache[url] = {
                'fingerprint': fp,
                'last_checked': time.time()
            }

            if old_fp is None:
                log.info(f"{name} — baseline captured")
                # On baseline — run AI if makers found to catch existing stock
                if is_homepage_junk(text):
                    log.info(f"{name} — homepage/nav detected, skipping AI")
                    continue
                if prefilter(text, keywords):
                    log.info(f"{name} — makers found on baseline, running AI analysis...")
                    result = analyze_page(name, url, text, makers_list)
                    if result and result.get('alert_worthy'):
                        new_items = filter_new_items(name, result.get('notable_items', []))
                        if new_items or not result.get('notable_items'):
                            result['notable_items'] = new_items
                            result['agent'] = 'web_watcher'
                            result['source'] = name
                            result['event'] = 'baseline_stock_found'
                            result['page_excerpt'] = text[:6000]
                            result['products'] = instock_products(products)
                            if result.get('priority') == 'critical':
                                result['priority'] = 'high'
                            write_alert(settings, result)
                            mark_items_seen(name, new_items)
                            # Record content-seen at baseline too, else the first
                            # later page change re-fires this same baseline stock.
                            baseline_summary = (result.get('page_summary') or '') + ((result.get('drop_announcement') or {}).get('description') or '')
                            mark_content_seen(name, baseline_summary)
                        else:
                            log.info(f"{name} — all notable items already seen, suppressing alert")
                continue

            if fp == old_fp:
                log.info(f"{name} — no change")
                continue

            # Page changed
            log.info(f"{name} — PAGE CHANGED")

            if is_homepage_junk(text):
                log.info(f"{name} — homepage/nav detected, skipping AI")
                continue

            if not prefilter(text, keywords):
                log.info(f"{name} — changed but no maker keywords, skipping AI")
                continue

            log.info(f"{name} — maker keywords found, sending to AI...")
            result = analyze_page(name, url, text, makers_list)

            if result is None:
                log.error(f"{name} — AI analysis failed")
                continue

            if result.get('alert_worthy'):
                new_items = filter_new_items(name, result.get('notable_items', []))
                if new_items or not result.get('notable_items'):
                    result['notable_items'] = new_items
                    result['agent'] = 'web_watcher'
                    result['source'] = name
                    result['event'] = 'page_changed'
                    result['page_excerpt'] = text[:6000]
                    result['products'] = instock_products(products)
                    summary = (result.get('page_summary') or '') + ((result.get('drop_announcement') or {}).get('description') or '')
                    if is_content_seen(name, summary):
                        log.info(f"{name} — content unchanged since last alert, suppressing duplicate")
                        continue
                    write_alert(settings, result)
                    mark_content_seen(name, summary)
                    mark_items_seen(name, new_items)
                else:
                    log.info(f"{name} — all notable items already seen, suppressing alert")
            else:
                log.info(f"{name} — AI says not alert worthy")

        # ── User-submitted URL watches ──────────────────���────────────────────
        if time.time() - last_user_reload > USER_SITES_RELOAD_INTERVAL:
            user_sites = load_user_sites(source_urls)
            last_user_reload = time.time()
            if user_sites:
                log.info(f"Tracking {len(user_sites)} user-submitted URL(s)")

        for uurl, usite in user_sites.items():
            uname = usite['name'] + ' (user)'
            user_kws = usite['keywords']

            last_checked = page_cache.get(uurl, {}).get('last_checked', 0)
            # Stale watches get throttled to hourly
            interval = USER_POLL_INTERVAL
            if stale_watch_count.get(uurl, 0) >= STALE_THRESHOLD:
                interval = STALE_INTERVAL
            if time.time() - last_checked < interval:
                continue

            sleep_time = random.randint(min_gap, min_gap + jitter)
            log.info(f"Checking user site {uname} in {sleep_time}s (keywords: {', '.join(user_kws)})...")
            time.sleep(sleep_time)

            text, products = collection_fetch.fetch_collection(uurl, fetch_page, log=log)
            if text is None:
                failure_count[uurl] = failure_count.get(uurl, 0) + 1
                # Record the attempt so a failing URL is throttled by the poll
                # interval instead of being re-hit every ~10s loop tick (no backoff).
                page_cache.setdefault(uurl, {})['last_checked'] = time.time()
                if failure_count[uurl] >= fail_thresh:
                    log.error(f"{uname} has failed {failure_count[uurl]} times in a row")
                continue

            failure_count[uurl] = 0

            fp = page_fingerprint(text, products)
            old_fp = page_cache.get(uurl, {}).get('fingerprint')

            page_cache[uurl] = {
                'fingerprint': fp,
                'last_checked': time.time()
            }

            if old_fp is not None and fp == old_fp:
                log.info(f"{uname} — no change")
                continue

            if old_fp is None:
                log.info(f"{uname} — baseline captured, running analysis...")
            else:
                log.info(f"{uname} — PAGE CHANGED")

            if is_homepage_junk(text):
                log.info(f"{uname} — homepage/nav detected, skipping AI")
                continue

            # Pre-filter: skip AI if none of the user's keywords appear in the page text
            text_lower = text.lower()
            kw_found = any(kw.lower() in text_lower for kw in user_kws)
            if not kw_found:
                log.info(f"{uname} — no keywords in page text, skipping AI")
                stale_watch_count[uurl] = stale_watch_count.get(uurl, 0) + 1
                if stale_watch_count[uurl] == STALE_THRESHOLD:
                    log.info(f"{uname} — {STALE_THRESHOLD} consecutive no-finds, throttling to hourly")
                continue

            result = analyze_user_page(uurl, text, user_kws)

            if result is None:
                log.error(f"{uname} — AI analysis failed")
                continue

            if result.get('alert_worthy'):
                stale_watch_count[uurl] = 0  # reset — found something
                summary = result.get('page_summary', '')
                if is_content_seen(uname, summary):
                    log.info(f"{uname} — content unchanged since last alert, suppressing")
                    continue
                new_items = filter_new_items(uname, result.get('notable_items', []))
                if new_items or not result.get('notable_items'):
                    result['notable_items'] = new_items
                    result['agent'] = 'web_watcher'
                    result['source'] = uname
                    result['event'] = 'user_watch_alert'
                    result['page_excerpt'] = text[:6000]
                    result['products'] = instock_products(products)
                    write_alert(settings, result)
                    mark_content_seen(uname, summary)
                    mark_items_seen(uname, new_items)
                else:
                    log.info(f"{uname} — all items already seen, suppressing")
            else:
                stale_watch_count[uurl] = stale_watch_count.get(uurl, 0) + 1
                if stale_watch_count[uurl] == STALE_THRESHOLD:
                    log.info(f"{uname} — {STALE_THRESHOLD} consecutive no-finds, throttling to hourly")
                else:
                    log.info(f"{uname} — not alert worthy ({stale_watch_count.get(uurl, 0)}/{STALE_THRESHOLD} stale)")

        time.sleep(10)

if __name__ == '__main__':
    run()
