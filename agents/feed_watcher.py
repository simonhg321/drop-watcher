# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
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
sys.path.insert(0, BASE_DIR)
import paths
import db
load_dotenv(paths.ENV_FILE)

# ── Add agents dir to path ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))
from ai_interpreter import analyze_page
from config_load import load_yaml, build_keywords, prefilter

# ── Paths ─────────────────────────────────────────────────────────────────────
CONFIG_DIR   = paths.CONFIG_DIR
LOG_DIR      = paths.LOG_DIR
SOURCES_FILE = paths.SOURCES_YAML
COOL_LIST_FILE = paths.COOL_LIST_YAML
MAKERS_FILE  = paths.MAKERS_YAML
SETTINGS_FILE = paths.SETTINGS_YAML

SEEN_FEEDS_FILE = paths.SEEN_FEEDS_JSON
DROPS_LOG       = paths.DROPS_JSONL

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

# Log to the file only. cron already redirects stdout+stderr to the same file
# (>> feed_watcher.log 2>&1), so a StreamHandler here duplicated every line.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'feed_watcher.log')),
    ]
)
log = logging.getLogger('feed_watcher')

# load_yaml / build_keywords / prefilter now live in config_load.py (shared with
# web_watcher so the two scrapers pre-filter identically). build_makers_list is local.
def build_makers_list(makers_config):
    return [maker['name'] for maker in makers_config.get('makers', [])]

# ── Seen entry tracking (via SQLite) ─────────────────────────────────────────
SEEN_TTL_HOURS = 72

def entry_key(feed_name, entry_id):
    raw = f"{feed_name}:{entry_id}"
    return hashlib.md5(raw.encode()).hexdigest()

def is_seen(key):
    return db.is_feed_seen(key, hours=SEEN_TTL_HOURS)

def mark_seen(key):
    db.mark_feed_seen(key)

# ── Alert writer (mirrors web_watcher) ───────────────────────────────────────
def write_alert(settings, alert):
    db.add_drop(alert)
    log.info(f"ALERT: {alert['source']} -- {alert.get('priority','?').upper()}")
    for item in alert.get('notable_items', []):
        log.info(f"   -> {item}")

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

            if is_seen(key):
                continue

            new_count += 1

            # Build text from title + summary
            title   = entry.get('title', '')
            summary = entry.get('summary', '')
            link    = entry.get('link', url)
            text    = f"{title}\n\n{summary}"

            if not prefilter(text, keywords):
                log.debug(f"  No keywords in: {title[:60]}")
                mark_seen(key)  # deterministic miss — safe to record
                continue

            log.info(f"  🎯 Keyword hit: {title[:80]}")

            result = analyze_page(
                site_name=name,
                url=link,
                page_text=text,
                makers_list=makers_list
            )

            if result is None:
                # Leave UNSEEN so a transient AI/API failure retries next run
                # instead of permanently swallowing a real drop.
                log.error(f"  AI analysis failed for entry: {title[:60]}")
                continue

            # AI returned a verdict — record it either way so we don't re-analyze.
            mark_seen(key)

            if result.get('alert_worthy'):
                result['agent']  = 'feed_watcher'
                result['source'] = name
                result['event']  = 'feed_entry'
                result['entry_title'] = title
                result['entry_url']   = link
                result['page_excerpt'] = text[:6000]
                write_alert(settings, result)
                log.info(f"  ✓ Alert written — {result.get('priority','?').upper()}")
            else:
                log.info(f"  AI says not alert worthy: {title[:60]}")

        log.info(f"{name} — {new_count} new entries processed")

    log.info("Feed Watcher done")

if __name__ == '__main__':
    run()
