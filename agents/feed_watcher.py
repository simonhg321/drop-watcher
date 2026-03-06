#!/usr/bin/env python3
"""
feed_watcher.py
Drop Watcher — RSS/Atom Feed Agent
Monitors Reddit and other feeds for knife and Steel Flame drops.
Run via cron every 15 minutes.
HGR
"""

import os
import sys
import json
import time
import logging
import hashlib
from datetime import datetime, timezone

import requests
import feedparser
import yaml
from dotenv import load_dotenv

# ── Load environment ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

# ── Add agents dir to path ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))
from ai_interpreter import analyze_page

# ── Paths ─────────────────────────────────────────────────────────────────────
CONFIG_DIR   = os.path.join(BASE_DIR, 'config')
LOG_DIR      = os.path.join(BASE_DIR, 'logs')
SOURCES_FILE = os.path.join(CONFIG_DIR, 'sources.yaml')
COOL_LIST_FILE = os.path.join(CONFIG_DIR, 'cool_list.yaml')
MAKERS_FILE  = os.path.join(CONFIG_DIR, 'makers.yaml')
SETTINGS_FILE = os.path.join(CONFIG_DIR, 'settings.yaml')

SEEN_FEEDS_FILE = os.path.join(LOG_DIR, 'seen_feeds.json')
DROPS_LOG       = os.path.join(LOG_DIR, 'drops.jsonl')

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'feed_watcher.log')),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('feed_watcher')

# ── YAML loader ───────────────────────────────────────────────────────────────
def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

# ── Build makers list and keywords (same as web_watcher) ─────────────────────
def build_makers_list(makers_config):
    return [maker['name'] for maker in makers_config.get('makers', [])]

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

def prefilter(text, keywords):
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)

# ── Seen entry tracking ───────────────────────────────────────────────────────
SEEN_TTL_HOURS = 72  # keep entry IDs for 3 days

def load_seen_feeds():
    if not os.path.exists(SEEN_FEEDS_FILE):
        return {}
    try:
        with open(SEEN_FEEDS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_seen_feeds(seen):
    with open(SEEN_FEEDS_FILE, 'w') as f:
        json.dump(seen, f)

def entry_key(feed_name, entry_id):
    raw = f"{feed_name}:{entry_id}"
    return hashlib.md5(raw.encode()).hexdigest()

def is_seen(key, seen):
    now = time.time()
    last = seen.get(key, 0)
    return (now - last) < SEEN_TTL_HOURS * 3600

def mark_seen(key, seen):
    now = time.time()
    seen[key] = now
    # Prune old entries
    cutoff = now - SEEN_TTL_HOURS * 3600
    return {k: v for k, v in seen.items() if v > cutoff}

# ── Alert writer (mirrors web_watcher) ───────────────────────────────────────
def write_alert(settings, alert):
    log_path = os.path.join(
        settings['logging']['log_dir'],
        settings['logging']['log_file']
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        f.write(json.dumps(alert) + '\n')

    log.info(f"🔥 ALERT: {alert['source']} — {alert.get('priority','?').upper()}")
    for item in alert.get('notable_items', []):
        log.info(f"   → {item}")

# ── Fetch RSS feed ────────────────────────────────────────────────────────────
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; personal use)'
}

def fetch_feed(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        return feed
    except Exception as e:
        log.warning(f"Failed to fetch feed {url}: {e}")
        return None

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    log.info("Feed Watcher starting — HGR")

    sources   = load_yaml(SOURCES_FILE)
    cool      = load_yaml(COOL_LIST_FILE)
    makers    = load_yaml(MAKERS_FILE)
    settings  = load_yaml(SETTINGS_FILE)

    keywords    = build_keywords(cool, makers)
    makers_list = build_makers_list(makers)
    seen        = load_seen_feeds()

    feeds = [f for f in sources.get('feeds', []) if f.get('enabled', True)]

    if not feeds:
        log.info("No enabled feeds found in sources.yaml — exiting")
        return

    log.info(f"Checking {len(feeds)} feeds | {len(keywords)} keywords | {len(makers_list)} makers")

    for feed_config in feeds:
        name = feed_config['name']
        url  = feed_config['url']

        if 'PLACEHOLDER' in url:
            log.info(f"Skipping {name} — placeholder URL")
            continue

        log.info(f"Fetching {name}...")
        feed = fetch_feed(url)

        if feed is None:
            log.warning(f"{name} — fetch failed")
            continue

        entries = feed.get('entries', [])
        log.info(f"{name} — {len(entries)} entries")

        new_count = 0
        for entry in entries:

            # Skip posts by site owner
            entry_author = entry.get('author', '').lower()
            if 'simonhg' in entry_author:
                log.info(f"  Skipping own post: {entry.get('title', '')[:60]}")
                continue
            entry_id = entry.get('id') or entry.get('link') or entry.get('title', '')
            key = entry_key(name, entry_id)

            if is_seen(key, seen):
                continue

            seen = mark_seen(key, seen)
            new_count += 1

            # Build text from title + summary
            title   = entry.get('title', '')
            summary = entry.get('summary', '')
            link    = entry.get('link', url)
            text    = f"{title}\n\n{summary}"

            if not prefilter(text, keywords):
                log.debug(f"  No keywords in: {title[:60]}")
                continue

            log.info(f"  🎯 Keyword hit: {title[:80]}")

            result = analyze_page(
                site_name=name,
                url=link,
                page_text=text,
                makers_list=makers_list
            )

            if result is None:
                log.error(f"  AI analysis failed for entry: {title[:60]}")
                continue

            if result.get('alert_worthy'):
                result['agent']  = 'feed_watcher'
                result['source'] = name
                result['event']  = 'feed_entry'
                result['entry_title'] = title
                result['entry_url']   = link
                write_alert(settings, result)
                log.info(f"  ✓ Alert written — {result.get('priority','?').upper()}")
            else:
                log.info(f"  AI says not alert worthy: {title[:60]}")

        log.info(f"{name} — {new_count} new entries processed")
        save_seen_feeds(seen)

    save_seen_feeds(seen)
    log.info("Feed Watcher done")

if __name__ == '__main__':
    run()
