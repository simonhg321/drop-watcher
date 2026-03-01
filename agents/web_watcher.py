#!/usr/bin/env python3
"""
web_watcher.py
Drop Watcher — Web Agent
Monitors websites for knife and Steel Flame drops.
HGR
"""

import os
import json
import time
import random
import logging
import hashlib
from datetime import datetime, timezone

import requests
import yaml
from bs4 import BeautifulSoup

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR  = os.path.join(BASE_DIR, 'config')
LOG_DIR     = os.path.join(BASE_DIR, 'logs')

SOURCES_FILE    = os.path.join(CONFIG_DIR, 'sources.yaml')
COOL_LIST_FILE  = os.path.join(CONFIG_DIR, 'cool_list.yaml')
MAKERS_FILE     = os.path.join(CONFIG_DIR, 'makers.yaml')
SETTINGS_FILE   = os.path.join(CONFIG_DIR, 'settings.yaml')

# ── Logging setup ─────────────────────────────────────────────────────────────
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


# ── Config loader ─────────────────────────────────────────────────────────────
def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


# ── Build flat keyword list ───────────────────────────────────────────────────
def build_keywords(cool_list, makers):
    keywords = []

    # From cool_list buckets
    for bucket in cool_list.get('keywords', {}).values():
        for kw in bucket:
            keywords.append(kw.lower())

    # Maker names and aliases
    for maker in makers.get('makers', []):
        keywords.append(maker['name'].lower())
        for alias in maker.get('aliases', []):
            keywords.append(alias.lower())

    # Collab keywords
    for collab in makers.get('collaborations', []):
        for alias in collab.get('aliases', []):
            keywords.append(alias.lower())

    return list(set(keywords))


# ── Page fingerprint (detect changes) ────────────────────────────────────────
def fingerprint(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


# ── Match keywords in text ────────────────────────────────────────────────────
def find_matches(text, keywords):
    text_lower = text.lower()
    return [kw for kw in keywords if kw in text_lower]


# ── Write alert to JSONL log ──────────────────────────────────────────────────
def write_alert(settings, alert):
    log_path = os.path.join(
        settings['logging']['log_dir'],
        settings['logging']['log_file']
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        f.write(json.dumps(alert) + '\n')
    log.info(f"🔥 ALERT: {alert['source']} — matched: {alert['matches']}")


# ── Fetch a single URL ────────────────────────────────────────────────────────
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; personal use)'
}

def fetch_page(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None


# ── Main watcher loop ─────────────────────────────────────────────────────────
def run():
    log.info("Web Watcher starting up — HGR")

    # Load configs
    sources  = load_yaml(SOURCES_FILE)
    cool     = load_yaml(COOL_LIST_FILE)
    makers   = load_yaml(MAKERS_FILE)
    settings = load_yaml(SETTINGS_FILE)

    keywords      = build_keywords(cool, makers)
    jitter        = settings['polling']['jitter_seconds']
    min_gap       = settings['polling']['min_domain_gap_seconds']
    fail_thresh   = settings['agent']['failure_threshold']
    retry_delay   = settings['agent']['retry_delay_seconds']

    log.info(f"Loaded {len(keywords)} keywords")
    log.info(f"Loaded {len(sources.get('websites', []))} websites")

    # Track page fingerprints so we only alert on changes
    page_cache    = {}
    failure_count = {}

    websites = [s for s in sources.get('websites', []) if s.get('enabled', True)]

    while True:
        for site in websites:
            name     = site['name']
            url      = site['url']
            interval = site.get('poll_interval', 20) * 60  # convert to seconds

            # Check if it's time to poll this site
            last_checked = page_cache.get(url, {}).get('last_checked', 0)
            if time.time() - last_checked < interval:
                continue

            # Polite jitter — randomize the actual wait
            sleep_time = random.randint(min_gap, min_gap + jitter)
            log.info(f"Checking {name} in {sleep_time}s...")
            time.sleep(sleep_time)

            # Fetch
            html = fetch_page(url)
            if html is None:
                failure_count[url] = failure_count.get(url, 0) + 1
                if failure_count[url] >= fail_thresh:
                    log.error(f"{name} has failed {failure_count[url]} times in a row")
                time.sleep(retry_delay)
                continue

            failure_count[url] = 0

            # Parse visible text
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)

            # Fingerprint — only process if page has changed
            fp = fingerprint(text)
            old_fp = page_cache.get(url, {}).get('fingerprint')

            page_cache[url] = {
                'fingerprint': fp,
                'last_checked': time.time()
            }

            if old_fp is None:
                log.info(f"{name} — baseline captured, watching for changes")
                continue

            if fp == old_fp:
                log.info(f"{name} — no change")
                continue

            # Page changed — check for keyword matches
            log.info(f"{name} — PAGE CHANGED, scanning...")
            matches = find_matches(text, keywords)

            if matches:
                alert = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'agent': 'web_watcher',
                    'source': name,
                    'url': url,
                    'matches': matches,
                    'priority': 'high' if any(m in ['hinderer steel flame', 'collab', 'collaboration'] for m in matches) else 'medium'
                }
                write_alert(settings, alert)
            else:
                log.info(f"{name} — changed but no keyword matches")

        # Short sleep before next loop iteration
        time.sleep(10)


if __name__ == '__main__':
    run()
