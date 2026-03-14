# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
paths.py — Single source of truth for all Drop Watcher file paths.
Every script imports from here. Change paths once, everything follows.

On ironman (production):
  CODE_DIR  = /home/shg/drop-watcher        (git repo, code only)
  CONFIG_DIR = /etc/drop-watcher             (secrets + config, 640)
  DATA_DIR  = /var/lib/drop-watcher          (runtime state + PII, 700)
  LOG_DIR   = /var/log/drop-watcher          (logs, 750)
  WWW_DIR   = /var/www/html                  (served files)

Override any path via environment variable (for local dev or testing).
HGR
"""

import os

CODE_DIR = os.environ.get(
    'DW_CODE_DIR',
    os.path.dirname(os.path.abspath(__file__))
)

CONFIG_DIR = os.environ.get(
    'DW_CONFIG_DIR',
    os.path.join(CODE_DIR, 'config')
)

DATA_DIR = os.environ.get(
    'DW_DATA_DIR',
    os.path.join(CODE_DIR, 'data')
)

LOG_DIR = os.environ.get(
    'DW_LOG_DIR',
    os.path.join(CODE_DIR, 'logs')
)

WWW_DIR = os.environ.get(
    'DW_WWW_DIR',
    '/var/www/html'
)

ENV_FILE = os.environ.get(
    'DW_ENV_FILE',
    os.path.join(CONFIG_DIR, '.env')
)

# ── Config files ────────────────────────────────────────────────────────────
SOURCES_YAML   = os.path.join(CONFIG_DIR, 'sources.yaml')
MAKERS_YAML    = os.path.join(CONFIG_DIR, 'makers.yaml')
COOL_LIST_YAML = os.path.join(CONFIG_DIR, 'cool_list.yaml')
SETTINGS_YAML  = os.path.join(CONFIG_DIR, 'settings.yaml')

# ── Data files (PII + runtime state) ───────────────────────────────────────
WATCHERS_JSON      = os.path.join(DATA_DIR, 'watchers.json')
WATCHERS_LOCK      = os.path.join(DATA_DIR, 'watchers.json.lock')
DROPS_JSONL        = os.path.join(LOG_DIR, 'drops.jsonl')
SEEN_ITEMS_JSON    = os.path.join(DATA_DIR, 'seen_items.json')
SEEN_CONTENT_JSON  = os.path.join(DATA_DIR, 'seen_content.json')
SEEN_FEEDS_JSON    = os.path.join(DATA_DIR, 'seen_feeds.json')
ALERTS_SENT_JSONL  = os.path.join(LOG_DIR, 'alerts_sent.jsonl')
SMS_SENT_JSONL     = os.path.join(LOG_DIR, 'sms_sent.jsonl')
WATCHDOG_STATE     = os.path.join(DATA_DIR, 'watchdog_state.json')
PREFLIGHT_JSONL    = os.path.join(LOG_DIR, 'preflight.jsonl')

# ── Output HTML ─────────────────────────────────────────────────────────────
ALERTS_HTML = os.path.join(WWW_DIR, 'alerts.html')
STATUS_HTML = os.path.join(WWW_DIR, 'status.html')
