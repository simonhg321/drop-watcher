# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
discord_logger.py
Drop Watcher — Discord Webhook Logger
Posts all new drops to a Discord channel.
Run via cron every 10 minutes (same as per_user_alerter).
HGR
"""

import json
import os
import hashlib
import logging
from datetime import datetime, timezone, timedelta

import httpx
import paths
import db

# ── Config ────────────────────────────────────────────────────────────────────
WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')

# Only post drops from the last 15 minutes (aligns with cron cycle)
WINDOW_MINUTES = 15

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s [discord] %(message)s')
log = logging.getLogger('discord_logger')

# ── Dedup tracking (via SQLite) ───────────────────────────────────────────────
def drop_id(drop):
    raw = f"{drop.get('timestamp', '')}|{drop.get('url', '')}|{drop.get('source', '')}"
    return hashlib.md5(raw.encode()).hexdigest()

def prune_sent(sent, hours=48):
    """Legacy compat — no longer needed with SQLite."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return {k: v for k, v in sent.items() if v > cutoff}

# ── Discord message formatting ────────────────────────────────────────────────
PRIORITY_COLORS = {
    'critical': 0xC0392B,  # ember red
    'high':     0xE67E22,  # flame orange
    'medium':   0xF1C40F,  # yellow
    'low':      0x888888,  # gray
}

PRIORITY_EMOJI = {
    'critical': '🔴',
    'high':     '🟠',
    'medium':   '🟡',
    'low':      '⚪',
}

def format_embed(drop):
    priority = (drop.get('priority') or 'medium').lower()
    source   = drop.get('source', 'Unknown')
    url      = drop.get('url', '')
    summary  = drop.get('page_summary', '')
    notable  = drop.get('notable_items', [])
    ts       = drop.get('timestamp', '')
    emoji    = PRIORITY_EMOJI.get(priority, '⚪')

    description = summary[:300] if summary else 'No summary available.'

    if notable:
        items_str = '\n'.join(f'• {item}' for item in notable[:5])
        description += f'\n\n**Notable:**\n{items_str}'

    embed = {
        'title': f'{emoji} {priority.upper()} — {source}',
        'description': description,
        'url': url,
        'color': PRIORITY_COLORS.get(priority, 0x888888),
        'footer': {'text': 'Drop Watcher — instockornot.club'},
    }

    if ts:
        embed['timestamp'] = ts

    return embed

# ── Post to Discord ───────────────────────────────────────────────────────────
def post_to_discord(embed):
    if not WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL not set — skipping")
        return False
    payload = {
        'username': 'Drop Watcher',
        'embeds': [embed],
    }
    try:
        r = httpx.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code == 204:
            return True
        elif r.status_code == 429:
            log.warning(f"Discord rate limited — retry after {r.json().get('retry_after', '?')}s")
            return False
        else:
            log.error(f"Discord webhook failed: {r.status_code} — {r.text[:200]}")
            return False
    except Exception as e:
        log.error(f"Discord webhook error: {e}")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    drops = db.get_recent_drops(minutes=WINDOW_MINUTES)
    posted = 0

    for drop in drops:
        did = drop_id(drop)
        if db.is_discord_sent(did):
            continue

        embed = format_embed(drop)
        if post_to_discord(embed):
            db.mark_discord_sent(did)
            posted += 1

    if posted:
        log.info(f"Posted {posted} drop(s) to Discord")

if __name__ == '__main__':
    run()
