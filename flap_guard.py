"""flap_guard.py — pause a watch that flaps: more than FLAP_MAX_EMAILS alerts in a
rolling FLAP_WINDOW_DAYS window with zero human outbound clicks (Simon 2026-07-17,
the umnumzaan grind). The watch is paused, not deleted — the pause email carries a
reactivate link, and reactivation restarts the counter (watchers.flap_reset_at).

Tunable from crontab env without a deploy:
  DW_FLAP_GUARD=0        kill switch (default on)
  DW_FLAP_MAX_EMAILS=5   pause on the email AFTER this many
  DW_FLAP_WINDOW_DAYS=4  rolling window
"""
import logging
import os
from datetime import timedelta
import db

log = logging.getLogger(__name__)

FLAP_MAX_EMAILS = int(os.environ.get('DW_FLAP_MAX_EMAILS', '5'))
FLAP_WINDOW_DAYS = float(os.environ.get('DW_FLAP_WINDOW_DAYS', '4'))


def enabled():
    return os.environ.get('DW_FLAP_GUARD', '1') != '0'


def should_pause(watcher, now):
    """True when this watch has sent more than FLAP_MAX_EMAILS in the window and
    the watcher has zero human outbound clicks in the same window. Fails open
    (never pauses) on any error — a DB hiccup must not kill a live watch."""
    if not enabled():
        return False
    try:
        window_start = (now - timedelta(days=FLAP_WINDOW_DAYS)).isoformat()
        since = max(window_start, watcher.get('flap_reset_at') or '')
        if db.count_watch_emails(watcher['id'], since) <= FLAP_MAX_EMAILS:
            return False
        if db.count_watch_clicks(watcher['id'], since) > 0:
            return False
        log.warning(f"FLAP_TRIPPED watcher={watcher['id']} email={watcher.get('email')} "
                    f"window={FLAP_WINDOW_DAYS}d max={FLAP_MAX_EMAILS}")
        return True
    except Exception as e:
        log.error(f"flap_guard check failed for {watcher.get('id')}, failing OPEN: {e}")
        return False
