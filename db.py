# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
db.py — SQLite database layer for Drop Watcher.
Replaces all JSON/JSONL file state with a single SQLite database.
WAL mode for concurrent readers, busy_timeout for writer contention.
HGR
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

import paths

DB_PATH = os.environ.get('DW_DB', os.path.join(paths.DATA_DIR, 'dropwatcher.db'))

# ── Schema ──────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchers (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    url TEXT NOT NULL,
    keywords TEXT NOT NULL,
    name TEXT DEFAULT '',
    priority TEXT DEFAULT 'high',
    phone TEXT DEFAULT '',
    sms_approved INTEGER DEFAULT 0,
    sms_verify_code TEXT,
    sms_verify_expires TEXT,
    active INTEGER DEFAULT 0,
    verify_token TEXT,
    unsubscribe_token TEXT NOT NULL,
    created TEXT NOT NULL,
    last_alert TEXT,
    alert_count INTEGER DEFAULT 0,
    consecutive_not_found INTEGER DEFAULT 0,
    last_acked TEXT,
    ageout_email_sent TEXT,
    maker TEXT
);
CREATE INDEX IF NOT EXISTS idx_watchers_email ON watchers(email);
CREATE INDEX IF NOT EXISTS idx_watchers_unsub_token ON watchers(unsubscribe_token);
CREATE INDEX IF NOT EXISTS idx_watchers_verify_token ON watchers(verify_token);
CREATE INDEX IF NOT EXISTS idx_watchers_active ON watchers(active);

CREATE TABLE IF NOT EXISTS drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    page_summary TEXT DEFAULT '',
    notable_items TEXT DEFAULT '[]',
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drops_timestamp ON drops(timestamp);
CREATE INDEX IF NOT EXISTS idx_drops_source ON drops(source);
CREATE INDEX IF NOT EXISTS idx_drops_priority ON drops(priority);

CREATE TABLE IF NOT EXISTS alert_hwm (
    consumer TEXT PRIMARY KEY,
    last_drop_id INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alert_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    alert_key TEXT NOT NULL,
    recipient TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_tracking_key ON alert_tracking(alert_key, alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_tracking_sent ON alert_tracking(sent_at);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    caller TEXT NOT NULL,
    site TEXT DEFAULT '',
    model TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_usage_ts ON api_usage(ts);

CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    caller TEXT NOT NULL,
    site TEXT DEFAULT '',
    url TEXT DEFAULT '',
    prompt_snippet TEXT DEFAULT '',
    response TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ai_calls_ts ON ai_calls(ts);

CREATE TABLE IF NOT EXISTS seen_content (
    content_key TEXT PRIMARY KEY,
    seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_items (
    item_key TEXT PRIMARY KEY,
    seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_feeds (
    feed_key TEXT PRIMARY KEY,
    seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discord_sent (
    drop_id TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pageviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vid TEXT NOT NULL,
    path TEXT NOT NULL,
    ref TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pageviews_ts ON pageviews(ts);

CREATE TABLE IF NOT EXISTS nkd_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watcher_id TEXT NOT NULL,
    drop_url TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    note TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    show_on_wall INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nkd_scores_wall ON nkd_scores(show_on_wall, scored_at);
CREATE INDEX IF NOT EXISTS idx_nkd_scores_watcher ON nkd_scores(watcher_id);

-- Candidate dealer domains discovered from user watches (dealer_scout.py).
-- This is a REVIEW QUEUE ONLY — nothing here is watched until a human copies it into
-- sources.yaml. Keeping it out of sources.yaml is what prevents an unreviewed domain
-- from triggering the curated cross-watcher fan-out.
CREATE TABLE IF NOT EXISTS dealer_candidates (
    domain TEXT PRIMARY KEY,
    is_dealer INTEGER DEFAULT 0,
    category TEXT DEFAULT '',
    brands TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    reason TEXT DEFAULT '',
    sample_url TEXT DEFAULT '',
    user_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',   -- pending | approved | rejected | promoted
    notified TEXT,                   -- ISO ts when Simon was nudged (once per domain)
    first_seen TEXT NOT NULL,
    last_checked TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dealer_candidates_status ON dealer_candidates(status);

CREATE TABLE IF NOT EXISTS outbound_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watcher_id TEXT NOT NULL,
    dest_url TEXT NOT NULL,
    dest_domain TEXT NOT NULL,
    source TEXT DEFAULT '',
    link_ts INTEGER,                 -- when the link was minted (email build)
    clicked_at TEXT NOT NULL,
    user_agent TEXT DEFAULT '',
    scanner INTEGER DEFAULT 0        -- 1 = probable email-scanner prefetch, not a human
);
CREATE INDEX IF NOT EXISTS idx_outbound_clicks_domain ON outbound_clicks(dest_domain, clicked_at);

CREATE TABLE IF NOT EXISTS alert_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key TEXT NOT NULL,            -- per_user_alerter.cooldown_key hash
    watcher_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    drop_url TEXT NOT NULL,
    matches TEXT NOT NULL,              -- comma-joined matched keywords
    recipient TEXT DEFAULT '',
    opened_at TEXT NOT NULL,
    closed_at TEXT,                     -- NULL = open; open episode = cooldown
    emails_sent INTEGER DEFAULT 1,
    last_email_at TEXT,
    engaged_at TEXT,                    -- first outbound click after the alert
    keep_delete_sent_at TEXT,
    matched_lines TEXT DEFAULT '[]'     -- JSON: notable_items line(s) that triggered (Corp #21 C self-heal)
);
CREATE INDEX IF NOT EXISTS idx_episodes_match_open
    ON alert_episodes(match_key) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_episodes_watcher
    ON alert_episodes(watcher_id, domain);

CREATE TABLE IF NOT EXISTS page_scans (
    url TEXT PRIMARY KEY,               -- latest scan per URL only
    domain TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    instock_text TEXT DEFAULT ''        -- everything observed purchasable this scan
);

CREATE TABLE IF NOT EXISTS sent_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    channel   TEXT NOT NULL DEFAULT 'email',
    ts        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sent_alerts_recip_ts ON sent_alerts(recipient, ts);

-- FTS5 product index (record_index.py) — one row per in-stock product per scan.
-- Rebuilt per source_url on each scan; only available=1 products are stored.
-- product_records_fts is a standalone FTS5 table (not external-content) that stores
-- its own copy of the searchable columns plus source_url for scoped deletes.
CREATE TABLE IF NOT EXISTS product_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    title TEXT, vendor TEXT, tags TEXT,
    url TEXT, price TEXT, available INTEGER DEFAULT 1,
    scanned_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_product_records_source ON product_records(source_url);
CREATE VIRTUAL TABLE IF NOT EXISTS product_records_fts USING fts5(
    source_url, title, vendor, tags
);
"""


# ── Connection ──────────────────────────────────────────────────────────────

def _init_db(conn):
    """Create tables if they don't exist."""
    conn.executescript(SCHEMA)
    _migrate(conn)


def _migrate(conn):
    """Add columns added after initial schema. Idempotent."""
    cols = {r['name'] for r in conn.execute("PRAGMA table_info(watchers)").fetchall()}
    for col, ddl in (
        ('last_acked',        'ALTER TABLE watchers ADD COLUMN last_acked TEXT'),
        ('ageout_email_sent', 'ALTER TABLE watchers ADD COLUMN ageout_email_sent TEXT'),
        ('maker',             'ALTER TABLE watchers ADD COLUMN maker TEXT'),
        ('strikes',           'ALTER TABLE watchers ADD COLUMN strikes INTEGER DEFAULT 0'),
    ):
        if col not in cols:
            conn.execute(ddl)

    # Legacy pre-ALTER rows have maker NULL (new rows ''); clients .toLowerCase()
    # on it. Normalise once so the class is gone.
    conn.execute("UPDATE watchers SET maker='' WHERE maker IS NULL")
    conn.execute("UPDATE watchers SET strikes=0 WHERE strikes IS NULL")

    click_cols = {r['name'] for r in conn.execute("PRAGMA table_info(outbound_clicks)").fetchall()}
    if 'scanner' not in click_cols:
        conn.execute("ALTER TABLE outbound_clicks ADD COLUMN scanner INTEGER DEFAULT 0")

    ep_cols = {r['name'] for r in conn.execute("PRAGMA table_info(alert_episodes)").fetchall()}
    if 'matched_lines' not in ep_cols:
        conn.execute("ALTER TABLE alert_episodes ADD COLUMN matched_lines TEXT DEFAULT '[]'")

    # Unique backstop for the signup check-then-act race (gunicorn -w 2): one
    # watch per (email, url, maker). Maker is part of the key because global
    # watches all share url=''. One-time dedup first — keep the active row,
    # else the oldest (verified 0 dupes in prod before shipping).
    conn.execute("""
        DELETE FROM watchers WHERE rowid NOT IN (
            SELECT rowid FROM (
                SELECT rowid, ROW_NUMBER() OVER (
                    PARTITION BY email, url, COALESCE(maker,'')
                    ORDER BY active DESC, rowid ASC) AS rn
                FROM watchers)
            WHERE rn = 1)""")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_watchers_email_url_maker
        ON watchers(email, url, COALESCE(maker,''))""")


_initialized_paths = set()  # DB paths whose schema this process has already ensured

@contextmanager
def get_db():
    """Get a database connection with WAL mode and busy timeout."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    # Schema is IF-NOT-EXISTS + an idempotent migration; running it on every conn
    # open (hundreds/hr across the cron fleet) is wasted work. Do it once per process
    # per DB path. (S51 P3a)
    if DB_PATH not in _initialized_paths:
        _init_db(conn)
        _initialized_paths.add(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Watchers ────────────────────────────────────────────────────────────────

def get_all_watchers():
    with get_db() as db:
        rows = db.execute("SELECT * FROM watchers").fetchall()
        return [dict(r) for r in rows]


def get_active_watchers():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM watchers WHERE active=1"
        ).fetchall()
        return [dict(r) for r in rows]


def get_watchers_by_email(email):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM watchers WHERE email=?", (email.lower(),)
        ).fetchall()
        return [dict(r) for r in rows]


def get_watcher_by_id(watcher_id):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM watchers WHERE id=?", (watcher_id,)
        ).fetchone()
        return dict(row) if row else None


def get_watcher_by_verify_token(token):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM watchers WHERE verify_token=?", (token,)
        ).fetchone()
        return dict(row) if row else None


def get_watcher_by_unsub_token(token):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM watchers WHERE unsubscribe_token=?", (token,)
        ).fetchone()
        return dict(row) if row else None


def get_watchers_by_unsub_token(token):
    """Get ALL watchers sharing an unsubscribe token (all watches for one email)."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM watchers WHERE unsubscribe_token=?", (token,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_watcher(watcher_dict):
    with get_db() as db:
        db.execute("""
            INSERT INTO watchers (id, email, url, keywords, name, priority, phone,
                sms_approved, sms_verify_code, sms_verify_expires, active, verify_token,
                unsubscribe_token, created, last_alert, alert_count, maker)
            VALUES (:id, :email, :url, :keywords, :name, :priority, :phone,
                :sms_approved, :sms_verify_code, :sms_verify_expires, :active, :verify_token,
                :unsubscribe_token, :created, :last_alert, :alert_count, :maker)
        """, {
            'id': watcher_dict['id'],
            'email': watcher_dict['email'],
            'url': watcher_dict['url'],
            'keywords': watcher_dict['keywords'],
            'name': watcher_dict.get('name', ''),
            'priority': watcher_dict.get('priority', 'high'),
            'phone': watcher_dict.get('phone', ''),
            'sms_approved': 1 if watcher_dict.get('sms_approved') else 0,
            'sms_verify_code': watcher_dict.get('sms_verify_code'),
            'sms_verify_expires': watcher_dict.get('sms_verify_expires'),
            'active': 1 if watcher_dict.get('active') else 0,
            'verify_token': watcher_dict.get('verify_token'),
            'unsubscribe_token': watcher_dict['unsubscribe_token'],
            'created': watcher_dict['created'],
            'last_alert': watcher_dict.get('last_alert'),
            'alert_count': watcher_dict.get('alert_count', 0),
            'maker': watcher_dict.get('maker', ''),
        })


WATCHER_UPDATABLE_FIELDS = {
    'keywords', 'priority', 'phone', 'name', 'maker',
    'sms_approved', 'sms_verify_code', 'sms_verify_expires',
    'active', 'verify_token',
    'last_alert', 'alert_count', 'consecutive_not_found',
    'last_acked', 'ageout_email_sent', 'strikes',
}


def update_watcher(watcher_id, **fields):
    """Update specific fields on a watcher. Pass field=value pairs."""
    if not fields:
        return
    bad = set(fields) - WATCHER_UPDATABLE_FIELDS
    if bad:
        raise ValueError(f"Cannot update field(s): {bad}")
    for k, v in fields.items():
        if isinstance(v, bool):
            fields[k] = 1 if v else 0
    set_clause = ', '.join(f'{k}=?' for k in fields)
    values = list(fields.values()) + [watcher_id]
    with get_db() as db:
        db.execute(f"UPDATE watchers SET {set_clause} WHERE id=?", values)


def update_watchers_by_email(email, **fields):
    """Update fields on ALL watchers for a given email."""
    if not fields:
        return
    bad = set(fields) - WATCHER_UPDATABLE_FIELDS
    if bad:
        raise ValueError(f"Cannot update field(s): {bad}")
    for k, v in fields.items():
        if isinstance(v, bool):
            fields[k] = 1 if v else 0
    set_clause = ', '.join(f'{k}=?' for k in fields)
    values = list(fields.values()) + [email.lower()]
    with get_db() as db:
        db.execute(f"UPDATE watchers SET {set_clause} WHERE email=?", values)


def revive_aged_out(email, now_iso):
    """Reactivate watches this email lost to age-out. Returns count revived.
    Only touches rows where ageout_email_sent IS NOT NULL — i.e. we nudged them.
    Unsubscribed or unverified watches (ageout_email_sent IS NULL) are untouched."""
    with get_db() as db:
        cur = db.execute("""
            UPDATE watchers SET active=1
            WHERE email=? AND active=0 AND ageout_email_sent IS NOT NULL
              AND (last_acked IS NULL OR last_acked < ageout_email_sent)
        """, (email.lower(),))
        return cur.rowcount


def delete_watcher(watcher_id):
    with get_db() as db:
        db.execute("DELETE FROM watchers WHERE id=?", (watcher_id,))


def find_watcher_by_email_url(email, url, maker=None):
    """Dedup lookup for signup. Global watches all share url='' — for those,
    maker is part of the identity (two global watches for different makers are
    different watches), so scope by maker too when url is empty."""
    q = "SELECT * FROM watchers WHERE email=? AND url=?"
    params = [email.lower(), url]
    if maker is not None and not url:
        q += " AND COALESCE(maker,'')=?"
        params.append(maker)
    with get_db() as db:
        row = db.execute(q, params).fetchone()
        return dict(row) if row else None


def activate_pending_watchers(email):
    """Activate only watches still awaiting verification (verify_token set).
    Unsubscribed watches (active=0, verify_token NULL) must NOT be resurrected
    by a later verify click — that's a consent violation."""
    with get_db() as db:
        db.execute(
            "UPDATE watchers SET active=1, verify_token=NULL "
            "WHERE email=? AND verify_token IS NOT NULL",
            (email.lower(),)
        )


def count_recent_new_shop_watches(email, hours, known_domains):
    """How many watches this email created in the last `hours` that point to a domain
    NOT in known_domains (i.e. new shops they introduced). For the signup abuse cap."""
    from urls import domain_from_url
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    known = {d.lower() for d in known_domains}
    with get_db() as db:
        rows = db.execute(
            "SELECT url FROM watchers WHERE email=? AND created>=?", (email.lower(), cutoff)
        ).fetchall()
    return sum(1 for r in rows if (r['url'] or '').strip()
               and domain_from_url(r['url']) not in known)


def get_sms_approved_watchers():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM watchers WHERE sms_approved=1 AND phone != ''"
        ).fetchall()
        return [dict(r) for r in rows]


def count_active_watchers():
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) as c FROM watchers WHERE active=1").fetchone()
        return row['c']


# ── Drops ───────────────────────────────────────────────────────────────────

def add_drop(drop_dict):
    """Write a drop alert. drop_dict is the full alert dict."""
    with get_db() as db:
        db.execute("""
            INSERT INTO drops (source, url, timestamp, priority, page_summary, notable_items, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            drop_dict.get('source', ''),
            drop_dict.get('url', ''),
            drop_dict.get('timestamp', ''),
            drop_dict.get('priority', 'medium'),
            drop_dict.get('page_summary', ''),
            json.dumps(drop_dict.get('notable_items', [])),
            json.dumps(drop_dict),
        ))


def get_recent_drops(minutes=None, hours=None):
    """Get drops within a time window. Returns list of full drop dicts."""
    if minutes:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    elif hours:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    else:
        cutoff = '1970-01-01'
    with get_db() as db:
        rows = db.execute(
            "SELECT raw_json FROM drops WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,)
        ).fetchall()
        return [json.loads(r['raw_json']) for r in rows]


def get_drops_count(hours=None):
    """Count drops, optionally within a time window."""
    if hours:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with get_db() as db:
            row = db.execute("SELECT COUNT(*) as c FROM drops WHERE timestamp >= ?", (cutoff,)).fetchone()
    else:
        with get_db() as db:
            row = db.execute("SELECT COUNT(*) as c FROM drops").fetchone()
    return row['c']


def get_drops_by_priority(hours=24):
    """Count drops by priority in the last N hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute("""
            SELECT priority, COUNT(*) as c FROM drops
            WHERE timestamp >= ? GROUP BY priority
        """, (cutoff,)).fetchall()
        return {r['priority']: r['c'] for r in rows}


def get_latest_drop_timestamp():
    with get_db() as db:
        row = db.execute("SELECT MAX(timestamp) as ts FROM drops").fetchone()
        return row['ts'] if row else None


def get_unprocessed_drops(consumer='per_user_alerter'):
    """Get all drops with id > last processed, oldest first. Never misses a drop."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT last_drop_id FROM alert_hwm WHERE consumer = ?",
            (consumer,)
        ).fetchone()
        hwm = row['last_drop_id'] if row else 0
        rows = conn.execute(
            "SELECT id, raw_json FROM drops WHERE id > ? ORDER BY id ASC",
            (hwm,)
        ).fetchall()
        return [(r['id'], json.loads(r['raw_json'])) for r in rows]


def set_hwm(consumer, drop_id):
    """Advance the high-water mark for a consumer."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO alert_hwm (consumer, last_drop_id) VALUES (?, ?) "
            "ON CONFLICT(consumer) DO UPDATE SET last_drop_id = excluded.last_drop_id",
            (consumer, drop_id)
        )


def trim_drops(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM drops WHERE timestamp < ?", (cutoff,))


# ── Alert tracking ──────────────────────────────────────────────────────────

def is_alert_sent(alert_key, alert_type='email'):
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM alert_tracking WHERE alert_key=? AND alert_type=?",
            (alert_key, alert_type)
        ).fetchone()
        return row is not None


def mark_alert_sent(alert_key, alert_type='email', recipient='', phone=''):
    with get_db() as db:
        db.execute("""
            INSERT INTO alert_tracking (alert_type, alert_key, recipient, phone, sent_at)
            VALUES (?, ?, ?, ?, ?)
        """, (alert_type, alert_key, recipient, phone,
              datetime.now(timezone.utc).isoformat()))


def is_cooldown_active(cooldown_key, hours=6):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        row = db.execute("""
            SELECT 1 FROM alert_tracking
            WHERE alert_key=? AND alert_type='per_user' AND sent_at > ?
        """, (cooldown_key, cutoff)).fetchone()
        return row is not None


def mark_cooldown(cooldown_key, recipient=''):
    mark_alert_sent(cooldown_key, alert_type='per_user', recipient=recipient)


# ── Alert episodes (spec 2026-06-12: episode-based cooldown) ─────────────────
# One open episode per (watcher, domain, matched keywords) = "the user already
# knows this item is in stock". Open episode replaces the old 6h timed cooldown;
# it closes when a scan observes the item not purchasable.

def open_episode(match_key, watcher_id, domain, drop_url, matches, recipient, now_iso,
                 matched_lines='[]'):
    with get_db() as db:
        cur = db.execute("""
            INSERT INTO alert_episodes
                (match_key, watcher_id, domain, drop_url, matches, recipient,
                 opened_at, emails_sent, last_email_at, matched_lines)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (match_key, watcher_id, domain, drop_url, matches, recipient,
              now_iso, now_iso, matched_lines))
        return cur.lastrowid


def get_open_episode(match_key):
    with get_db() as db:
        row = db.execute("""
            SELECT * FROM alert_episodes
            WHERE match_key=? AND closed_at IS NULL
            ORDER BY id DESC LIMIT 1
        """, (match_key,)).fetchone()
        return dict(row) if row else None


def get_open_episodes():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM alert_episodes WHERE closed_at IS NULL ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def close_episode(episode_id, now_iso):
    with get_db() as db:
        db.execute("UPDATE alert_episodes SET closed_at=? WHERE id=? AND closed_at IS NULL",
                   (now_iso, episode_id))


def bump_episode_email(episode_id, now_iso):
    with get_db() as db:
        db.execute("""UPDATE alert_episodes
                      SET emails_sent=emails_sent+1, last_email_at=?
                      WHERE id=?""", (now_iso, episode_id))


def stamp_engagement(watcher_id, domain, now_iso):
    """A verified outbound click: mark this watcher's open episodes on the domain
    engaged (first click wins) and reset the watch's strike counter."""
    with get_db() as db:
        db.execute("""UPDATE alert_episodes
                      SET engaged_at=COALESCE(engaged_at, ?)
                      WHERE watcher_id=? AND domain=? AND closed_at IS NULL""",
                   (now_iso, watcher_id, domain))
        db.execute("UPDATE watchers SET strikes=0, last_acked=? WHERE id=?",
                   (now_iso, watcher_id))


def episodes_awaiting_keep_delete(cutoff_iso):
    """Open, engaged episodes whose engagement is older than cutoff and whose
    keep-or-delete email hasn't been sent."""
    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM alert_episodes
            WHERE closed_at IS NULL AND keep_delete_sent_at IS NULL
              AND engaged_at IS NOT NULL AND engaged_at <= ?
            ORDER BY id
        """, (cutoff_iso,)).fetchall()
        return [dict(r) for r in rows]


def mark_keep_delete_sent(episode_id, now_iso):
    with get_db() as db:
        db.execute("UPDATE alert_episodes SET keep_delete_sent_at=? WHERE id=?",
                   (now_iso, episode_id))


# ── Page scans (latest in-stock observation per URL) ─────────────────────────

def record_page_scan(url, domain, instock_text, now_iso):
    with get_db() as db:
        db.execute("""INSERT OR REPLACE INTO page_scans (url, domain, scanned_at, instock_text)
                      VALUES (?, ?, ?, ?)""", (url, domain, now_iso, instock_text))


def get_page_scan(url):
    with get_db() as db:
        row = db.execute("SELECT * FROM page_scans WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None


def touch_page_scan(url, now_iso):
    """Refresh scanned_at without changing instock_text — for fingerprint-unchanged
    pages, where the previous observation provably still holds. Keeps hourly
    reminders alive while an item sits in stock on a static page."""
    with get_db() as db:
        db.execute("UPDATE page_scans SET scanned_at=? WHERE url=?", (now_iso, url))


def is_sms_sent(alert_id, phone):
    with get_db() as db:
        row = db.execute("""
            SELECT 1 FROM alert_tracking
            WHERE alert_key=? AND alert_type='sms' AND phone=?
        """, (alert_id, phone)).fetchone()
        return row is not None


def mark_sms_sent(alert_id, phone):
    mark_alert_sent(alert_id, alert_type='sms', phone=phone)


def get_recent_alerts_sent(limit=20):
    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM alert_tracking
            WHERE alert_type='email'
            ORDER BY sent_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def trim_alert_tracking(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM alert_tracking WHERE sent_at < ?", (cutoff,))


# ── API usage ───────────────────────────────────────────────────────────────

def log_api_usage(caller, site, model, input_tokens, output_tokens):
    with get_db() as db:
        db.execute("""
            INSERT INTO api_usage (ts, caller, site, model, input_tokens, output_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), caller, site, model,
              input_tokens, output_tokens))


def get_api_usage_summary(hours=None):
    """Get aggregated API usage stats."""
    result = {
        'total_calls': 0, 'total_in': 0, 'total_out': 0,
        'calls_24h': 0, 'in_24h': 0, 'out_24h': 0,
    }
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) as c, COALESCE(SUM(input_tokens),0) as i, COALESCE(SUM(output_tokens),0) as o FROM api_usage").fetchone()
        result['total_calls'] = row['c']
        result['total_in'] = row['i']
        result['total_out'] = row['o']

        row = db.execute("SELECT COUNT(*) as c, COALESCE(SUM(input_tokens),0) as i, COALESCE(SUM(output_tokens),0) as o FROM api_usage WHERE ts >= ?", (cutoff_24h,)).fetchone()
        result['calls_24h'] = row['c']
        result['in_24h'] = row['i']
        result['out_24h'] = row['o']
    return result


def get_api_usage_by_caller():
    with get_db() as db:
        rows = db.execute("""
            SELECT caller, COUNT(*) as calls,
                   SUM(input_tokens) as inp, SUM(output_tokens) as outp
            FROM api_usage GROUP BY caller
        """).fetchall()
        return {r['caller']: {'calls': r['calls'], 'in': r['inp'], 'out': r['outp']} for r in rows}


def get_api_usage_by_day(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute("""
            SELECT SUBSTR(ts, 1, 10) as day, COUNT(*) as calls,
                   SUM(input_tokens) as inp, SUM(output_tokens) as outp
            FROM api_usage WHERE ts >= ?
            GROUP BY day ORDER BY day
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]


def trim_api_usage(days=90):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM api_usage WHERE ts < ?", (cutoff,))


# ── AI calls ────────────────────────────────────────────────────────────────

def log_ai_call(caller, site, url, prompt_snippet, response_json):
    with get_db() as db:
        db.execute("""
            INSERT INTO ai_calls (ts, caller, site, url, prompt_snippet, response)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), caller, site, url,
              prompt_snippet[:1000], json.dumps(response_json) if isinstance(response_json, dict) else str(response_json)))


def get_recent_ai_calls(limit=20):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM ai_calls ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_ai_calls(today_only=False):
    with get_db() as db:
        if today_only:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            row = db.execute("SELECT COUNT(*) as c FROM ai_calls WHERE ts >= ?", (today,)).fetchone()
        else:
            row = db.execute("SELECT COUNT(*) as c FROM ai_calls").fetchone()
        return row['c']


def trim_ai_calls(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM ai_calls WHERE ts < ?", (cutoff,))


# ── Seen content / items / feeds ────────────────────────────────────────────

def is_content_seen(content_key, hours=4):
    import time
    cutoff = time.time() - hours * 3600
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM seen_content WHERE content_key=? AND seen_at > ?",
            (content_key, cutoff)
        ).fetchone()
        return row is not None


def mark_content_seen(content_key):
    import time
    with get_db() as db:
        db.execute("""
            INSERT OR REPLACE INTO seen_content (content_key, seen_at)
            VALUES (?, ?)
        """, (content_key, time.time()))


def prune_seen_content(hours=8):
    import time
    cutoff = time.time() - hours * 3600
    with get_db() as db:
        db.execute("DELETE FROM seen_content WHERE seen_at < ?", (cutoff,))


def is_item_seen(item_key, hours=24):
    import time
    cutoff = time.time() - hours * 3600
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM seen_items WHERE item_key=? AND seen_at > ?",
            (item_key, cutoff)
        ).fetchone()
        return row is not None


def mark_item_seen(item_key):
    import time
    with get_db() as db:
        db.execute("""
            INSERT OR REPLACE INTO seen_items (item_key, seen_at)
            VALUES (?, ?)
        """, (item_key, time.time()))


def prune_seen_items(hours=48):
    import time
    cutoff = time.time() - hours * 3600
    with get_db() as db:
        db.execute("DELETE FROM seen_items WHERE seen_at < ?", (cutoff,))


def is_feed_seen(feed_key, hours=72):
    import time
    cutoff = time.time() - hours * 3600
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM seen_feeds WHERE feed_key=? AND seen_at > ?",
            (feed_key, cutoff)
        ).fetchone()
        return row is not None


def mark_feed_seen(feed_key):
    import time
    with get_db() as db:
        db.execute("""
            INSERT OR REPLACE INTO seen_feeds (feed_key, seen_at)
            VALUES (?, ?)
        """, (feed_key, time.time()))


def prune_seen_feeds(hours=72):
    import time
    cutoff = time.time() - hours * 3600
    with get_db() as db:
        db.execute("DELETE FROM seen_feeds WHERE seen_at < ?", (cutoff,))


# ── Discord sent ────────────────────────────────────────────────────────────

def is_discord_sent(drop_id):
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM discord_sent WHERE drop_id=?", (drop_id,)
        ).fetchone()
        return row is not None


def mark_discord_sent(drop_id):
    with get_db() as db:
        db.execute("""
            INSERT OR IGNORE INTO discord_sent (drop_id, sent_at)
            VALUES (?, ?)
        """, (drop_id, datetime.now(timezone.utc).isoformat()))


def prune_discord_sent(hours=48):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM discord_sent WHERE sent_at < ?", (cutoff,))


# ── Pageviews ───────────────────────────────────────────────────────────────

def add_pageview(vid, path, ref, ip):
    with get_db() as db:
        db.execute("""
            INSERT INTO pageviews (vid, path, ref, ip, ts)
            VALUES (?, ?, ?, ?, ?)
        """, (vid, path, ref, ip, datetime.now(timezone.utc).isoformat()))


def get_pageviews(hours=24):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM pageviews WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_unique_visitors(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT COUNT(DISTINCT vid) as c FROM pageviews WHERE ts >= ?", (cutoff,)
        ).fetchone()
        return row['c']


def trim_pageviews(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM pageviews WHERE ts < ?", (cutoff,))


# ── SMS stats ───────────────────────────────────────────────────────────────

def get_sms_stats():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) as c FROM alert_tracking WHERE alert_type='sms'").fetchone()['c']
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        recent = db.execute("SELECT COUNT(*) as c FROM alert_tracking WHERE alert_type='sms' AND sent_at >= ?", (cutoff,)).fetchone()['c']
        last = db.execute("SELECT sent_at FROM alert_tracking WHERE alert_type='sms' ORDER BY sent_at DESC LIMIT 1").fetchone()
        return {
            'total_sent': total,
            'sent_24h': recent,
            'last_sent': last['sent_at'] if last else None,
        }


# ── Trimming (replaces trim_drops.py for all tables) ───────────────────────

def trim_all():
    """Run all retention trims. Call from cron daily."""
    trim_drops(days=30)
    trim_alert_tracking(days=7)
    trim_api_usage(days=90)
    trim_ai_calls(days=30)
    trim_pageviews(days=30)
    prune_seen_content(hours=8)
    prune_seen_items(hours=48)
    prune_seen_feeds(hours=72)
    prune_discord_sent(hours=48)


# ── Dealer candidates (dealer_scout.py review queue) ───────────────────────

def get_dealer_candidate(domain):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM dealer_candidates WHERE domain=?", (domain,)
        ).fetchone()
        return dict(row) if row else None


def upsert_dealer_candidate(domain, is_dealer, category, brands, confidence,
                            reason, sample_url, user_count):
    """Insert or refresh a candidate. Preserves first_seen, status and notified
    across re-scans — only the classification fields and counts update."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute("""
            INSERT INTO dealer_candidates
                (domain, is_dealer, category, brands, confidence, reason,
                 sample_url, user_count, status, notified, first_seen, last_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                is_dealer=excluded.is_dealer,
                category=excluded.category,
                brands=excluded.brands,
                confidence=excluded.confidence,
                reason=excluded.reason,
                sample_url=excluded.sample_url,
                user_count=excluded.user_count,
                last_checked=excluded.last_checked
        """, (domain, int(is_dealer), category, brands, confidence, reason,
              sample_url, user_count, now, now))


def get_dealer_candidates(status=None, dealers_only=False):
    q = "SELECT * FROM dealer_candidates"
    conds, args = [], []
    if status:
        conds.append("status=?"); args.append(status)
    if dealers_only:
        conds.append("is_dealer=1")
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY user_count DESC, confidence DESC"
    with get_db() as db:
        return [dict(r) for r in db.execute(q, args).fetchall()]


def set_dealer_candidate_status(domain, status):
    with get_db() as db:
        db.execute("UPDATE dealer_candidates SET status=? WHERE domain=?",
                   (status, domain))


def mark_dealer_candidate_notified(domain):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute("UPDATE dealer_candidates SET notified=? WHERE domain=?",
                   (now, domain))


# ── Per-recipient send cap (daily_cap.py) ───────────────────────────────────

def record_sent_alert(recipient, channel='email', ts=None):
    from datetime import datetime, timezone
    ts = ts or datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute("INSERT INTO sent_alerts (recipient, channel, ts) VALUES (?,?,?)",
                   (recipient.lower(), channel, ts))


def count_sent_alerts(recipient, since_iso):
    with get_db() as db:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM sent_alerts WHERE recipient=? AND ts>=?",
            (recipient.lower(), since_iso)).fetchone()
        return row['n']
