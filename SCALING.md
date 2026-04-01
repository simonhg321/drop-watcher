# Drop Watcher Scaling Plan
# instockornot.club — From 61 watches to 10,000+
# Drafted 2026-04-01

---

## Current State

- 61 active watches, ~50 curated sources, $5 server (ironman)
- ~2,500 requests/day, ~$1.50/day API cost
- Everything single-threaded, file-based, cron-driven
- No database, no async, no queues
- Works perfectly at current scale

## What Breaks and When

| Watches | What Dies | Why |
|---------|-----------|-----|
| ~100 | fcntl lock contention | 4+ processes fighting over watchers.json — no timeout, indefinite waits |
| ~200 | web_watcher cycle time | Sequential scraping: 200 URLs × 30s timeout = 100 min, cron fires every 10 |
| ~500 | per_user_alerter matching | 500 watchers × 50 drops = 25,000 domain+keyword checks, all sequential |
| ~1000 | JSONL file scans | already_sent() linear scan on every alert, files grow unbounded |
| ~5000 | Memory pressure | Full watchers.json + drops.jsonl loaded into RAM on every cron run |
| ~10k+ | Single server ceiling | CPU/memory/disk all maxed, need to split services |

---

## Phase 1 — Quick Wins (No Architecture Change)

**Goal:** Buy runway to ~200 watches. Half-day of work.

### 1.1 — Add timeout to fcntl.flock

**Files:** `watcher_io.py`

Currently fcntl.flock blocks forever if another process holds the lock. Add a signal-based timeout so processes fail fast instead of hanging the whole pipeline.

```python
import signal

class LockTimeout(Exception):
    pass

def _timeout_handler(signum, frame):
    raise LockTimeout("Failed to acquire lock within timeout")

def load_watchers(timeout=10):
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)
    try:
        # existing lock code
        ...
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
```

**Risk:** Low. Worst case a cron run skips one cycle.

### 1.2 — In-memory dedup cache for alerter

**Files:** `alerter.py`, `per_user_alerter.py`

Currently `already_sent()` scans the entire `alerts_sent.jsonl` file for every single alert. Load it once into a set at the start of each run.

```python
def load_sent_cache():
    sent = set()
    with open(ALERTS_SENT_JSONL) as f:
        for line in f:
            entry = json.loads(line)
            sent.add(entry["alert_id"])
    return sent
```

Same pattern for `sms_sent.jsonl` in `sms_alerter.py` and `per_user_sent.json` in `per_user_alerter.py`.

**Impact:** O(1) dedup lookups instead of O(n) file scans per alert.

### 1.3 — JSONL retention / rotation

**Files:** `trim_drops.py` (already exists for drops.jsonl — extend pattern)

Add trimming for ALL unbounded JSONL files:

| File | Current Size | Retention | Trim Schedule |
|------|-------------|-----------|---------------|
| `drops.jsonl` | trimmed to 30 days | 30 days | daily 4am (already done) |
| `alerts_sent.jsonl` | unbounded | 7 days | daily 4am |
| `sms_sent.jsonl` | unbounded | 30 days | daily 4am |
| `api_usage.jsonl` | unbounded | 90 days | daily 4am |
| `ai_calls.jsonl` | unbounded, includes full prompts | 30 days | daily 4am |
| `pageviews.jsonl` | unbounded | 30 days | daily 4am |

Write one `trim_logs.py` that handles all of them. Add to the existing 4am cron slot.

**Impact:** Caps disk growth. ai_calls.jsonl is the big one — full prompts mean it could hit 500MB+ in a year.

### 1.4 — Retry with backoff on email/SMS sends

**Files:** `alerter.py`, `sms_alerter.py`

Currently if Resend or Twilio fails, the alert is lost forever. Add simple retry:

```python
def send_with_retry(fn, *args, max_retries=3, backoff=2):
    for attempt in range(max_retries):
        try:
            return fn(*args)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff ** attempt)
```

**Impact:** Prevents silent alert loss on transient API failures.

---

## Phase 2 — SQLite Migration

**Goal:** Replace all JSON state files with SQLite. Get to ~1000 watches. Full session of work.

### 2.1 — Database schema

**New file:** `db.py` — single source of truth for all database access.

```sql
-- watchers (replaces watchers.json)
CREATE TABLE watchers (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    url TEXT NOT NULL,
    keywords TEXT NOT NULL,  -- JSON array
    unsubscribe_token TEXT NOT NULL,
    verify_token TEXT,
    verified INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    sms_approved INTEGER DEFAULT 0,
    phone TEXT,
    priority TEXT DEFAULT 'medium',
    created_at TEXT NOT NULL,
    last_alert TEXT,
    alert_count INTEGER DEFAULT 0,
    consecutive_not_found INTEGER DEFAULT 0
);
CREATE INDEX idx_watchers_email ON watchers(email);
CREATE INDEX idx_watchers_token ON watchers(unsubscribe_token);
CREATE INDEX idx_watchers_active ON watchers(active, verified);

-- drops (replaces drops.jsonl)
CREATE TABLE drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    priority TEXT NOT NULL,
    page_summary TEXT,
    notable_items TEXT,  -- JSON array
    raw_json TEXT        -- full original entry for backward compat
);
CREATE INDEX idx_drops_timestamp ON drops(timestamp);
CREATE INDEX idx_drops_source ON drops(source);
CREATE INDEX idx_drops_priority ON drops(priority);

-- alert_tracking (replaces alerts_sent.jsonl, sms_sent.jsonl, per_user_sent.json)
CREATE TABLE alert_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,  -- 'email', 'sms', 'per_user'
    alert_key TEXT NOT NULL,   -- dedup key (alert_id or cooldown_key)
    recipient TEXT,
    sent_at TEXT NOT NULL
);
CREATE INDEX idx_alert_tracking_key ON alert_tracking(alert_key, alert_type);
CREATE INDEX idx_alert_tracking_sent ON alert_tracking(sent_at);

-- api_usage (replaces api_usage.jsonl)
CREATE TABLE api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_api_usage_timestamp ON api_usage(timestamp);

-- seen_content (replaces seen_content.json, seen_feeds.json)
CREATE TABLE seen_content (
    content_key TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
```

### 2.2 — Migration script

**New file:** `bin/migrate_to_sqlite.py`

1. Read watchers.json → INSERT INTO watchers
2. Read drops.jsonl → INSERT INTO drops
3. Read alerts_sent.jsonl → INSERT INTO alert_tracking (type='email')
4. Read sms_sent.jsonl → INSERT INTO alert_tracking (type='sms')
5. Read per_user_sent.json → INSERT INTO alert_tracking (type='per_user')
6. Read api_usage.jsonl → INSERT INTO api_usage
7. Read seen_content.json → INSERT INTO seen_content

Keep old files as `.bak` for rollback. Run on ironman, verify counts match.

### 2.3 — db.py interface

Keep the interface simple — thin wrappers, not an ORM:

```python
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DW_DB", "/var/lib/drop-watcher/dropwatcher.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # concurrent readers
    conn.execute("PRAGMA busy_timeout=5000")  # 5s retry on lock
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_active_watchers():
    with get_db() as db:
        return db.execute(
            "SELECT * FROM watchers WHERE active=1 AND verified=1"
        ).fetchall()

def add_drop(source, url, timestamp, priority, summary, items, raw):
    with get_db() as db:
        db.execute(
            "INSERT INTO drops (source, url, timestamp, priority, page_summary, notable_items, raw_json) VALUES (?,?,?,?,?,?,?)",
            (source, url, timestamp, priority, summary, json.dumps(items), json.dumps(raw))
        )

def is_already_sent(alert_key, alert_type):
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM alert_tracking WHERE alert_key=? AND alert_type=?",
            (alert_key, alert_type)
        ).fetchone()
        return row is not None
```

### 2.4 — Files to update

Every file that touches watchers.json or JSONL files needs to switch to db.py:

| File | Changes |
|------|---------|
| `watcher_signup.py` | Replace watchers.json read/write with db calls. Remove fcntl. |
| `per_user_alerter.py` | Replace watchers.json + per_user_sent.json + drops.jsonl reads with queries. |
| `alerter.py` | Replace drops.jsonl read + alerts_sent.jsonl scan with queries. |
| `sms_alerter.py` | Replace watchers.json read + sms_sent.jsonl scan with queries. |
| `agents/web_watcher.py` | Replace seen_content.json + drops.jsonl append + watchers.json read with db calls. |
| `agents/feed_watcher.py` | Replace seen_feeds.json + drops.jsonl append with db calls. |
| `agents/ai_interpreter.py` | Replace api_usage.jsonl append with db call. |
| `generate_alerts.py` | Query drops table instead of reading drops.jsonl. |
| `generate_traffic.py` | Query api_usage + drops tables. |
| `generate_public_stats.py` | Query aggregates from db. |
| `generate_simon_status.py` | Query watchers + drops + api_usage from db. |
| `discord_logger.py` | Replace discord_sent.json with alert_tracking table. |
| `watcher_io.py` | Retire entirely — replaced by db.py. |
| `paths.py` | Add DB_PATH, remove JSONL paths (keep for backward compat during migration). |
| `trim_drops.py` | Replace with `DELETE FROM drops WHERE timestamp < ?`. |

### 2.5 — SQLite WAL mode

Key advantage: **WAL (Write-Ahead Logging) mode allows concurrent readers while one writer is active.** This eliminates the fcntl lock contention problem entirely.

- Multiple cron jobs can READ the database simultaneously
- Only one writer at a time, but writers don't block readers
- `busy_timeout=5000` means writers retry for 5 seconds before failing (vs fcntl's infinite block)

### 2.6 — Backup strategy

```bash
# Add to cron, daily at 3am (before trim_drops)
sqlite3 /var/lib/drop-watcher/dropwatcher.db ".backup /var/lib/drop-watcher/backups/dropwatcher-$(date +%Y%m%d).db"
# Keep 7 days of backups
find /var/lib/drop-watcher/backups/ -name "*.db" -mtime +7 -delete
```

### 2.7 — Test updates

Update `tests/test_core.py` to use SQLite fixtures instead of JSON temp files. Add:
- Test concurrent reads (should not block)
- Test write contention (should retry, not hang)
- Test migration script (JSON → SQLite round-trip)

---

## Phase 3 — Parallel Scraping

**Goal:** web_watcher processes multiple sites concurrently. Get to ~2000 watches. Half-day of work.

### 3.1 — ThreadPoolExecutor for web_watcher

**File:** `agents/web_watcher.py`

Replace the sequential loop with a thread pool:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def scrape_all_sources(sources, makers, cool_list):
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(scrape_one_source, src, makers, cool_list): src
            for src in sources
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                result = future.result(timeout=60)
                if result:
                    results.append(result)
            except Exception as e:
                log.error(f"Failed {src['name']}: {e}")
    return results
```

**Why threads not async:** The scraping code uses `requests` + `BeautifulSoup` — rewriting to `httpx` async would touch every function. Threads give 80% of the benefit with 10% of the work. `requests` releases the GIL during I/O so threads actually parallelize network waits.

### 3.2 — Separate user watch scraping

Split web_watcher into two loops that can run independently:

1. **Curated sources** — sources.yaml, 10-30 min intervals, knife-expert AI prompt
2. **User watches** — watchers table, 15 min intervals, generic AI prompt

These can run as separate supervisor processes or separate cron jobs. Benefit: a slow user URL doesn't delay curated source checks.

### 3.3 — AI call batching (optional)

If Anthropic adds batch API support for Haiku, batch multiple page analyses into one request. Current pattern is one API call per page — at 200 pages that's 200 sequential API calls even with parallel fetching.

Short term: just let the thread pool handle it. Each thread does its own AI call. Anthropic rate limits are generous for Haiku.

---

## Phase 4 — Async Alerting

**Goal:** Alerts send in parallel, never block each other. Quarter-day of work.

### 4.1 — Threaded email sends in per_user_alerter

```python
from concurrent.futures import ThreadPoolExecutor

def send_alerts_parallel(alerts_by_email):
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = []
        for email, alerts in alerts_by_email.items():
            futures.append(pool.submit(send_user_alert, email, alerts))
        for f in futures:
            try:
                f.result(timeout=30)
            except Exception as e:
                log.error(f"Alert send failed: {e}")
```

### 4.2 — Decouple SMS from email path

SMS already fires independently (session 27 fix). Verify it stays decoupled after SQLite migration — both should read from the drops table, not from each other's output.

---

## Phase 5 — Future (When You Need It)

These are not worth building until you're past ~5000 watches or have specific pain points.

### 5.1 — Message queue (Redis)

Decouple scraping → alerting pipeline:
- web_watcher publishes drops to Redis queue
- per_user_alerter consumes from queue
- Enables horizontal scaling (multiple scraper workers)

### 5.2 — FastAPI migration

Replace Flask + gunicorn with FastAPI + uvicorn:
- Native async support
- WebSocket support for live alerts page
- Better performance under load

### 5.3 — PostgreSQL

When SQLite's single-writer model becomes a bottleneck (~10k concurrent writes/min):
- Full MVCC concurrency
- Network-accessible (split services across servers)
- pg_notify for real-time alert triggers

### 5.4 — Worker nodes

Split scraping across multiple machines:
- Coordinator assigns URL batches to workers
- Workers POST results back to central API
- Central DB aggregates drops

---

## Session Checklist

When you're ready to attack, start a session and say:
> "Continuing Drop Watcher dev — scaling session. Start with Phase X."

### Phase 1 checklist (half-day)
- [ ] Add lock timeout to watcher_io.py
- [ ] In-memory dedup cache in alerter.py
- [ ] In-memory dedup cache in per_user_alerter.py
- [ ] In-memory dedup cache in sms_alerter.py
- [ ] Write trim_logs.py for all JSONL files
- [ ] Add trim_logs.py to 4am cron
- [ ] Add retry+backoff to alerter.py sends
- [ ] Add retry+backoff to sms_alerter.py sends
- [ ] Run test suite, verify nothing broke
- [ ] Deploy to ironman

### Phase 2 checklist (full session)
- [ ] Write db.py with schema + helpers
- [ ] Write bin/migrate_to_sqlite.py
- [ ] Update watcher_signup.py → db.py
- [ ] Update per_user_alerter.py → db.py
- [ ] Update alerter.py → db.py
- [ ] Update sms_alerter.py → db.py
- [ ] Update agents/web_watcher.py → db.py
- [ ] Update agents/feed_watcher.py → db.py
- [ ] Update agents/ai_interpreter.py → db.py
- [ ] Update all generate_*.py → db.py
- [ ] Update discord_logger.py → db.py
- [ ] Update paths.py with DB_PATH
- [ ] Retire watcher_io.py
- [ ] Update trim_drops.py → SQL DELETE
- [ ] Update tests/test_core.py for SQLite
- [ ] Add SQLite backup to cron
- [ ] Run migration on ironman (keep .bak files)
- [ ] Verify all cron jobs work with SQLite
- [ ] Monitor for 24h before removing .bak files

### Phase 3 checklist (half-day)
- [ ] Add ThreadPoolExecutor to web_watcher.py
- [ ] Split curated vs user watch loops
- [ ] Update supervisor config if splitting processes
- [ ] Load test with 200 dummy watches
- [ ] Monitor ironman CPU/memory under parallel load

### Phase 4 checklist (quarter-day)
- [ ] Threaded email sends in per_user_alerter.py
- [ ] Verify SMS stays decoupled
- [ ] Load test alert pipeline with 100 simultaneous matches

---

## What NOT to Change

These patterns are solid and should survive all phases:

- **drops as source of truth** — whether JSONL or SQLite table, drops are the canonical record
- **Two-track AI interpretation** — curated (knife expert) vs user (generic) prompts
- **One token per email** — all watches for an email share one dashboard link
- **AI interprets, human decides** — Claude flags, you buy
- **SMS is a nudge** — "check your email", not the full alert
- **Keyword pre-filter** — skip AI calls when no keywords match raw text
- **Homepage detection** — skip junk pages, save Haiku tokens
- **Stale watch throttling** — back off on consecutive "not found"
- **Atomic writes** — tmp+replace pattern (SQLite handles this natively)

---

## Cost Projections

| Watches | AI Calls/Day | Haiku Cost/Day | Resend Emails/Day | Server |
|---------|-------------|----------------|-------------------|--------|
| 61 | ~500 | ~$1.50 | ~20 | $5 VPS |
| 200 | ~1,500 | ~$4.50 | ~60 | $5 VPS |
| 500 | ~3,500 | ~$10.50 | ~150 | $10 VPS |
| 1000 | ~7,000 | ~$21.00 | ~300 | $20 VPS |
| 5000 | ~35,000 | ~$105.00 | ~1,500 | $40 VPS + worker |

Haiku is cheap. The real cost driver at scale is email (Resend free tier = 100/day, paid = $20/mo for 50k).
