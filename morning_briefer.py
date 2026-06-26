# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
Morning briefer — reads overnight alerts from drops.jsonl,
generates AI briefing, emails it.
Run via cron at 7am daily.
HGR
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from agents.ai_interpreter import generate_morning_briefing
from alerter import send_email

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('morning_briefer')

LOOKBACK_HOURS = 24

def load_overnight_alerts():
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT source, url, timestamp, priority FROM drops "
            "WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,)
        ).fetchall()
    return [
        {"source": r[0], "url": r[1], "timestamp": r[2], "priority": r[3]}
        for r in rows
    ]

def main():
    log.info("Morning briefer starting...")
    alerts = load_overnight_alerts()
    log.info(f"Found {len(alerts)} alerts in last {LOOKBACK_HOURS}h")

    sites_checked = len(set(a.get('source', '') for a in alerts if a.get('source')))
    briefing = generate_morning_briefing(alerts, sites_checked)
    log.info(f"Briefing: {briefing[:80]}...")

    import html as html_mod
    subject = f"Drop Watcher — {datetime.now().strftime('%a %b %d')}"
    body_html = f"<pre style='font-family:monospace'>{html_mod.escape(briefing)}</pre>"
    send_email(subject, body_html, briefing)
    log.info("Morning brief sent.")

if __name__ == '__main__':
    main()
