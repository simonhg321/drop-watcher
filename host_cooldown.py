# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
host_cooldown.py — fleet-law compliance for outbound fetches (Corp directive 207, task #31).

  * USER_AGENT  — one honest UA per MACHINE (hostname baked in), so a block on one
                  box never takes out the others. The old shared fleet-wide UA string
                  is retired everywhere; import this constant instead.
  * is_blocked  — is this URL's host inside a 24h cooldown?
  * record_429  — start (or extend) a 24h per-host cooldown, append blocked.log,
                  email Simon ONCE per block. Never raises.

Modeled on hgr-watch's hgrwatch.fetch/cooldown (Simon 2026-07-29: per-host backoff
+ retry + log, NOT a global halt). State lives in the main SQLite DB so the
supervisord daemon and the cron fetchers share one view and it survives restarts.
HGR
"""
import logging
import os
import socket
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import db
import paths

MACHINE = os.environ.get('DW_MACHINE') or socket.gethostname()
USER_AGENT = (f'Mozilla/5.0 (compatible; DropWatcher-{MACHINE}/2.0; '
              f'+https://instockornot.club; ops@instockornot.club)')

COOLDOWN_HOURS = 24
BLOCKED_LOG = os.path.join(paths.DATA_DIR, 'blocked.log')

log = logging.getLogger('host_cooldown')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS host_cooldowns (
    host        TEXT PRIMARY KEY,
    blocked_at  TEXT NOT NULL,
    retry_after TEXT NOT NULL,
    last_url    TEXT,
    hits        INTEGER NOT NULL DEFAULT 1
)
"""


def host_of(url):
    h = (urlparse(url).hostname or '').lower()
    return h[4:] if h.startswith('www.') else h


def _now(now):
    return now or datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec='seconds')


def is_blocked(url, now=None):
    host = host_of(url)
    if not host:
        return False
    try:
        with db.get_db() as conn:
            conn.execute(_SCHEMA)
            row = conn.execute("SELECT retry_after FROM host_cooldowns WHERE host=?",
                               (host,)).fetchone()
    except Exception as e:  # DB trouble must never stop a fetch
        log.warning(f"host_cooldown lookup failed for {host}: {e}")
        return False
    if not row:
        return False
    return _now(now) < datetime.fromisoformat(row['retry_after'])


def record_429(url, now=None):
    """Called on any 429. Opens a new cooldown (log + alert) or counts a hit
    inside an existing one (log only). Never raises."""
    host = host_of(url)
    now = _now(now)
    retry_after = now + timedelta(hours=COOLDOWN_HOURS)
    new_block = True
    try:
        with db.get_db() as conn:
            conn.execute(_SCHEMA)
            row = conn.execute("SELECT retry_after FROM host_cooldowns WHERE host=?",
                               (host,)).fetchone()
            if row and now < datetime.fromisoformat(row['retry_after']):
                new_block = False
                conn.execute("UPDATE host_cooldowns SET hits=hits+1, last_url=? WHERE host=?",
                             (url, host))
            else:
                conn.execute("""INSERT INTO host_cooldowns(host, blocked_at, retry_after, last_url, hits)
                                VALUES (?,?,?,?,1)
                                ON CONFLICT(host) DO UPDATE SET blocked_at=excluded.blocked_at,
                                  retry_after=excluded.retry_after, last_url=excluded.last_url, hits=1""",
                             (host, _iso(now), _iso(retry_after), url))
    except Exception as e:
        log.error(f"host_cooldown: failed to persist 429 for {host}: {e}")
    _log_block(now, host, url, retry_after if new_block else None)
    if new_block:
        log.warning(f"429 from {host} — backing off {COOLDOWN_HOURS}h (other hosts continue)")
        try:
            _alert(f"[drop-watcher/{MACHINE}] 429 from {host} — {COOLDOWN_HOURS}h backoff",
                   f"429 from {url}\n{host} is backed off until {_iso(retry_after)} UTC. "
                   f"Polling of other hosts continues.\nLog: {BLOCKED_LOG}")
        except Exception as e:
            log.error(f"host_cooldown: alert failed (backoff still applies): {e!r}")


def _log_block(now, host, url, retry_after):
    tag = f"retry_after={_iso(retry_after)}" if retry_after else "within_cooldown"
    try:
        os.makedirs(os.path.dirname(BLOCKED_LOG), exist_ok=True)
        with open(BLOCKED_LOG, 'a') as f:
            f.write(f"{_iso(now)}\t{host}\t429\t{tag}\turl={url}\n")
    except OSError as e:
        log.error(f"host_cooldown: cannot write {BLOCKED_LOG}: {e}")


def _alert(subject, body):
    from alerter import send_email   # lazy: alerter pulls in SMS/env at import
    return send_email(subject, f"<pre>{body}</pre>", body)
