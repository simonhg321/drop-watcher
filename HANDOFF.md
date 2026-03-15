# Drop Watcher — Project Map

What every file does, so future-Simon knows where to look.

---

## How it runs

```
cron (every 10 min)
  └─ web_watcher.py    → scrapes sites, writes drops.jsonl
  └─ feed_watcher.py   → checks RSS/Reddit feeds, writes drops.jsonl
  └─ per_user_alerter  → reads drops.jsonl, matches against watchers, emails users

cron (every 2 min)
  └─ watchdog.py       → checks gunicorn + web_watcher are alive, restarts if dead

cron (daily 7am)
  └─ morning_briefer   → AI summary of overnight drops, emails you

cron (daily 4am)
  └─ trim_drops.py     → prunes drops.jsonl to 30 days

Apache (instockornot.club)
  └─ /var/www/html/*.html   → static pages (copied from html/)
  └─ /api/*                 → reverse proxy to gunicorn:5001 (watcher_signup.py)
```

---

## Core Python — the engine

| File | What it does |
|------|-------------|
| `watcher_signup.py` | Flask API. Signup, verify, unsubscribe, resend-link, my-alerts, stats. The whole public API. |
| `per_user_alerter.py` | Reads drops.jsonl, matches drops to watchers by domain+keywords, emails users. Per-URL-per-keyword cooldown. |
| `alerter.py` | Sends alert emails (critical/high immediate, daily digest) via Resend. |
| `sms_alerter.py` | Sends SMS for CRITICAL drops via Twilio. Called by alerter. Waiting on A2P approval. |
| `paths.py` | Single source of truth for all file paths. Uses env vars with fallbacks. |
| `safe_fetch.py` | SSRF protection — blocks private IPs, metadata endpoints. Used by signup URL checker. |
| `watchdog.py` | Self-healing. Checks gunicorn + web_watcher every 2 min, restarts if dead. |
| `generate_alerts.py` | Builds the alerts.html page from drops.jsonl. One entry per source per day. |
| `morning_briefer.py` | AI-generated overnight summary, emailed at 7am. |
| `preflight.py` | Health checks before agents start. Non-blocking diagnostics. |
| `orchestrator.py` | **DEAD FILE** (BUG-008). Empty. Delete it. |

## Agents — the watchers

| File | What it does |
|------|-------------|
| `agents/web_watcher.py` | Scrapes sites from sources.yaml every 10-30 min. Writes drops to drops.jsonl. |
| `agents/ai_interpreter.py` | Claude AI analyzes page content — distinguishes real drops from routine restocks. |
| `agents/feed_watcher.py` | Monitors RSS/Reddit feeds for drops. Writes to drops.jsonl. |

## HTML — the frontend

All in `html/`, deployed to `/var/www/html/` on ironman.

| File | What it does |
|------|-------------|
| `index.html` | Landing page. "Give it a URL and your keywords." |
| `watchlist.html` | Signup form. URL check, keywords, email, priority. |
| `my-alerts.html` | Personal dashboard. Shows watches + matched drops. Token-based. |
| `get-my-link.html` | "Lost your link?" — enter email, get dashboard link resent. |
| `privacy.html` | Privacy policy + SMS terms (Twilio A2P 10DLC compliant). |
| `hgr.html` | About page — how Drop Watcher got built. |
| `alerts.html` | Public alerts feed. **Old design — not yet unified.** |
| `status.html` | System status page. **Old design — not yet unified.** |

## Config

All in `config/`, deployed to `/etc/drop-watcher/` on ironman.

| File | What it does |
|------|-------------|
| `sources.yaml` | URLs and feeds to monitor (knife dealers, Reddit, makers). |
| `makers.yaml` | Maker/brand info for AI interpretation. |
| `cool_list.yaml` | Special items to flag as CRITICAL. |
| `settings.yaml` | General settings (intervals, thresholds). |

## Ops scripts — `bin/`

| File | What it does |
|------|-------------|
| `bulk_watch.py` | Bulk-create watchers from sources.yaml for a given email. |
| `normalize_tokens.py` | One-time migration — unified 56 watches under one token per email. Already ran. |
| `trim_drops.py` | 30-day retention for drops.jsonl. Cron daily at 4am. |
| `cleanup_ironman.sh` | Removes dead files from ironman (orchestrator.py, watcher_status.html, test files, web/). |
| `migrate_dirs.sh` | One-time migration to new directory structure (/var/lib, /var/log, /etc). Already ran. |
| `reset_drops.sh` | Nukes drops.jsonl. Emergency use only. |

## Supervisor config — `conf/`

| File | What it does |
|------|-------------|
| `drop-watcher.conf` | Supervisord config. Runs web_watcher + gunicorn (5 workers). Deploy to `/etc/supervisor/conf.d/`. |

## Data files (on ironman, not in git)

| File | Where | What |
|------|-------|------|
| `watchers.json` | `/var/lib/drop-watcher/` | All watcher signups. PII. File-locked. |
| `drops.jsonl` | `/var/lib/drop-watcher/` | Every drop detected. Single source of truth. |
| `per_user_sent.json` | `/var/lib/drop-watcher/` | Cooldown tracker for per-user alerts. Auto-prunes 24h. |
| `.env` | `/etc/drop-watcher/` | Secrets (Resend key, Twilio creds, Claude key). |

## Dead files to clean up

| File | Status |
|------|--------|
| `orchestrator.py` | Empty file. BUG-008. In cleanup script. |
| `watcher_status.html` | Old status page. In cleanup script. |
| `web/` | Stale old directory. BUG-007. In cleanup script. |
| `test-escape.py`, `test-xss-cmd.sh`, `test-xss.json` | Old security tests. Can delete. |
| `nuke_watchers.sh` | Dangerous. Probably shouldn't exist. |
| `sessions`, `sessions.save` | Session files. Local only. |
| `.zshrc` | Your zshrc somehow ended up in the repo. |
| `.cleanup.sh` | Old cleanup script. |

## Key architecture decisions

- **One token per email** — all watches for simonhg@gmail.com share one unsubscribe_token = one dashboard link
- **drops.jsonl is the single source of truth** — per_user_alerter reads it, never re-scrapes
- **Cooldown is per watcher+URL+keyword combo** — a Damascus alert doesn't suppress a Steel Flame alert
- **File locking, not a database** — fcntl locks on watchers.json, atomic writes via tmp+replace
- **AI interprets, human decides** — Claude flags drops and priorities, but every purchase decision is yours
