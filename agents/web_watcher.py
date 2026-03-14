# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
web_watcher.py
Drop Watcher — Web Agent
Monitors websites for knife and Steel Flame drops.
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
load_dotenv(paths.ENV_FILE)

# ── Add agents dir to path so we can import ai_interpreter ───────────────────
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))
from ai_interpreter import analyze_page

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
def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

# ── Build makers list for AI ──────────────────────────────────────────────────
def build_makers_list(makers_config):
    return [maker['name'] for maker in makers_config.get('makers', [])]

# ── Build keyword list for pre-filter ────────────────────────────────────────
def build_keywords(cool_list, makers_config):
    keywords = []
    for bucket in cool_list.get('keywords', {}).values():
        for kw in bucket:
            keywords.append(kw.lower())
    for maker in makers_config.get('makers', []):
        keywords.append(maker['name'].lower())
        for alias in maker.get('aliases', []):
            keywords.append(alias.lower())
    for collab in makers_config.get('collaborations', []):
        for alias in collab.get('aliases', []):
            keywords.append(alias.lower())
    return list(set(keywords))

# ── Page fingerprint ──────────────────────────────────────────────────────────
def fingerprint(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

# ── Pre-filter ────────────────────────────────────────────────────────────────
def prefilter(text, keywords):
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


# ── Item deduplication ────────────────────────────────────────────────────────
SEEN_ITEMS_FILE = paths.SEEN_ITEMS_JSON
SEEN_CONTENT_FILE = paths.SEEN_CONTENT_JSON
CONTENT_DEDUP_HOURS = 4  # suppress same-content alerts from same source for 4 hours

def load_seen_content():
    if os.path.exists(SEEN_CONTENT_FILE):
        with open(SEEN_CONTENT_FILE) as f:
            return json.load(f)
    return {}

def save_seen_content(seen):
    with open(SEEN_CONTENT_FILE, 'w') as f:
        json.dump(seen, f)

def is_content_seen(source, summary, seen_content):
    """Return True if we've alerted on very similar content from this source recently."""
    import time
    key = f"{source}:{hashlib.md5(summary.encode()).hexdigest()[:8]}"
    last_seen = seen_content.get(key, 0)
    return (time.time() - last_seen) < CONTENT_DEDUP_HOURS * 3600

def mark_content_seen(source, summary, seen_content):
    import time
    key = f"{source}:{hashlib.md5(summary.encode()).hexdigest()[:8]}"
    seen_content[key] = time.time()
    cutoff = time.time() - CONTENT_DEDUP_HOURS * 3600 * 2
    return {k: v for k, v in seen_content.items() if v > cutoff}
DEDUP_HOURS = 24

def load_seen_items():
    if not os.path.exists(SEEN_ITEMS_FILE):
        return {}
    try:
        with open(SEEN_ITEMS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_seen_items(seen):
    with open(SEEN_ITEMS_FILE, 'w') as f:
        json.dump(seen, f)

def item_key(source, item):
    """Fingerprint a notable item per source."""
    raw = f"{source}:{item[:80].lower()}"
    return hashlib.md5(raw.encode()).hexdigest()

def filter_new_items(source, notable_items, seen):
    """Return only items not seen in the last DEDUP_HOURS."""
    now = time.time()
    new_items = []
    for item in notable_items:
        key = item_key(source, item)
        last_seen = seen.get(key, 0)
        if now - last_seen > DEDUP_HOURS * 3600:
            new_items.append(item)
    return new_items

def mark_items_seen(source, notable_items, seen):
    """Record items as seen right now."""
    now = time.time()
    for item in notable_items:
        key = item_key(source, item)
        seen[key] = now
    # Prune old entries (older than 48h)
    cutoff = now - 48 * 3600
    seen = {k: v for k, v in seen.items() if v > cutoff}
    return seen

# ── Alert writer ──────────────────────────────────────────────────────────────
def write_alert(settings, alert):
    log_path = os.path.join(
        settings['logging']['log_dir'],
        settings['logging']['log_file']
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        f.write(json.dumps(alert) + '\n')

    log.info(f"🔥 ALERT: {alert['source']}")
    if alert.get('notable_items'):
        for item in alert['notable_items']:
            log.info(f"   → {item}")
    if alert.get('drop_announcement', {}).get('detected'):
        drop = alert['drop_announcement']
        log.info(f"   🔥 DROP: {drop.get('maker')} — {drop.get('description')} — {drop.get('timing')}")

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

def fetch_page(url, ssl_permissive=False):
    try:
        session = requests.Session()
        if ssl_permissive:
            session.mount('https://', PermissiveSSLAdapter())
            log.debug(f"Using permissive SSL for {url}")
        response = session.get(
            url,
            headers=HEADERS,
            timeout=15,
            verify=not ssl_permissive
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None

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
    seen_items    = load_seen_items()
    seen_content  = load_seen_content()

    websites = [s for s in sources.get('websites', []) if s.get('enabled', True)]

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

            html = fetch_page(url, ssl_permissive=ssl_permissive)
            if html is None:
                failure_count[url] = failure_count.get(url, 0) + 1
                if failure_count[url] >= fail_thresh:
                    log.error(f"{name} has failed {failure_count[url]} times in a row")
                time.sleep(retry_delay)
                continue

            failure_count[url] = 0

            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup(['nav', 'header', 'footer', 'script', 'style', 'meta', 'link']):
                 tag.decompose()
            text = soup.get_text(separator=' ', strip=True)
            fp     = fingerprint(text)
            old_fp = page_cache.get(url, {}).get('fingerprint')

            page_cache[url] = {
                'fingerprint': fp,
                'last_checked': time.time()
            }

            if old_fp is None:
                log.info(f"{name} — baseline captured")
                # On baseline — run AI if makers found to catch existing stock
                if prefilter(text, keywords):
                    log.info(f"{name} — makers found on baseline, running AI analysis...")
                    result = analyze_page(name, url, text, makers_list)
                    if result and result.get('alert_worthy'):
                        new_items = filter_new_items(name, result.get('notable_items', []), seen_items)
                        if new_items or not result.get('notable_items'):
                            result['notable_items'] = new_items
                            result['agent'] = 'web_watcher'
                            result['source'] = name
                            result['event'] = 'baseline_stock_found'
                            # Baseline events never fire CRITICAL — we haven't confirmed real availability yet
                            if result.get('priority') == 'critical':
                                result['priority'] = 'high'
                            write_alert(settings, result)
                            seen_items = mark_items_seen(name, new_items, seen_items)
                            save_seen_items(seen_items)
                        else:
                            log.info(f"{name} — all notable items already seen, suppressing alert")
                continue

            if fp == old_fp:
                log.info(f"{name} — no change")
                continue

            # Page changed
            log.info(f"{name} — PAGE CHANGED")

            if not prefilter(text, keywords):
                log.info(f"{name} — changed but no maker keywords, skipping AI")
                continue

            log.info(f"{name} — maker keywords found, sending to AI...")
            result = analyze_page(name, url, text, makers_list)

            if result is None:
                log.error(f"{name} — AI analysis failed")
                continue

            if result.get('alert_worthy'):
                new_items = filter_new_items(name, result.get('notable_items', []), seen_items)
                if new_items or not result.get('notable_items'):
                    result['notable_items'] = new_items
                    result['agent'] = 'web_watcher'
                    result['source'] = name
                    result['event'] = 'page_changed'
                    summary = result.get('page_summary', '') + result.get('drop_announcement', {}).get('description', '')
                    if is_content_seen(name, summary, seen_content):
                        log.info(f"{name} — content unchanged since last alert, suppressing duplicate")
                        continue
                    write_alert(settings, result)
                    seen_content = mark_content_seen(name, summary, seen_content)
                    save_seen_content(seen_content)
                    seen_items = mark_items_seen(name, new_items, seen_items)
                    save_seen_items(seen_items)
                else:
                    log.info(f"{name} — all notable items already seen, suppressing alert")
            else:
                log.info(f"{name} — AI says not alert worthy")

        time.sleep(10)

if __name__ == '__main__':
    run()
