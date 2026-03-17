#!/usr/bin/env python3
# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
cleanup_stale.py — Remove pending (unverified) watches older than 2 hours.
Catches typo'd emails, bots, and people who never clicked verify.
Run via cron every 30 min: */30 * * * *
NOTE: 2h is aggressive — if we scale and email delivery slows, bump this up.
HGR
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from watcher_io import load_watchers, save_watchers

STALE_HOURS = 2

logging.basicConfig(level=logging.INFO, format='%(asctime)s [cleanup_stale] %(message)s')
log = logging.getLogger(__name__)


def run():
    watchers = load_watchers()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)).isoformat()
    before = len(watchers)

    stale = [w for w in watchers if not w.get('active') and (w.get('created', '') < cutoff)]
    keep = [w for w in watchers if w.get('active') or (w.get('created', '') >= cutoff)]

    removed = before - len(keep)
    if removed:
        save_watchers(keep)
        for w in stale:
            log.info(f"Removed stale: {w.get('email')} | {w.get('url', '')[:60]} | created {w.get('created', '?')}")
        log.info(f"Cleaned {removed} stale pending watch(es). {len(keep)} remain.")
    else:
        log.info(f"No stale watches. {before} total.")


if __name__ == '__main__':
    run()
