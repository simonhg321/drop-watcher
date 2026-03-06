#!/usr/bin/env python3
"""
generate_alerts.py
Drop Watcher — Alerts Page Generator
Reads drops.jsonl and generates a live alerts page.
Run via cron every 30 seconds or called from web_watcher after each alert.
HGR
"""

import os
import json
from datetime import datetime, timezone, timedelta

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LOG_DIR     = os.path.join(BASE_DIR, 'logs')
DROPS_LOG   = os.path.join(LOG_DIR, 'drops.jsonl')
WWW_DIR     = '/var/www/html'
ALERTS_HTML = os.path.join(WWW_DIR, 'alerts.html')

HOURS_BACK  = 48

# ── Priority styles ───────────────────────────────────────────────────────────
PRIORITY_COLOR = {
    'critical': '#e74c3c',
    'high':     '#e67e22',
    'medium':   '#f1c40f',
    'low':      '#888',
}

PRIORITY_LABEL = {
    'critical': '🔥 CRITICAL',
    'high':     '⚡ HIGH',
    'medium':   '· MEDIUM',
    'low':      '· LOW',
}

def load_recent_alerts(hours=48):
    alerts = []
    if not os.path.exists(DROPS_LOG):
        return alerts

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with open(DROPS_LOG, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alert = json.loads(line)
                # Skip raw keyword-only alerts — AI enriched only
                if not alert.get("notable_items") and not alert.get("drop_announcement", {}).get("detected") and not alert.get("page_summary"):
                    continue
                ts_str = alert.get('timestamp', '')
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts > cutoff:
                        alerts.append(alert)
            except json.JSONDecodeError:
                continue

    # Newest first
    alerts.sort(key=lambda a: a.get('timestamp', ''), reverse=True)
    return alerts

def format_timestamp(ts_str):
    try:
        ts = datetime.fromisoformat(ts_str)
        return ts.strftime('%Y-%m-%d %H:%M UTC')
    except:
        return ts_str

def render_alert_card(alert):
    priority    = alert.get('priority', 'medium').lower()
    source      = alert.get('source', 'Unknown')
    url         = alert.get('url', '#')
    ts          = format_timestamp(alert.get('timestamp', ''))
    event       = alert.get('event', 'page_changed')
    color       = PRIORITY_COLOR.get(priority, '#888')
    label       = PRIORITY_LABEL.get(priority, priority.upper())

    # Notable items (AI layer)
    notable_items = alert.get('notable_items', [])
    notable_html = ''
    if notable_items:
        items_html = ''.join(f'<li>{item}</li>' for item in notable_items)
        notable_html = f'<ul class="notable-items">{items_html}</ul>'

    # Drop announcement (AI layer)
    drop = alert.get('drop_announcement', {})
    drop_html = ''
    if drop and drop.get('detected'):
        maker   = drop.get('maker', '')
        desc    = drop.get('description', '')
        timing  = drop.get('timing', '')
        conf    = drop.get('confidence', '')
        drop_html = f"""
        <div class="drop-announcement">
            🔥 DROP ANNOUNCEMENT — {maker}: {desc}
            {f'<span class="timing">⏰ {timing}</span>' if timing else ''}
            {f'<span class="confidence">confidence: {conf}</span>' if conf else ''}
        </div>"""

    # Keyword matches (old layer fallback)
    matches = alert.get('matches', [])
    matches_html = ''
    if matches and not notable_items:
        matches_html = f'<div class="matches">matched: {", ".join(matches[:10])}</div>'

    # Page summary (AI layer)
    summary = alert.get('page_summary', '')
    summary_html = f'<div class="summary">{summary}</div>' if summary else ''

    # Makers found
    makers_found = alert.get('makers_found', [])
    makers_html = ''
    if makers_found:
        makers_html = f'<div class="makers-found">makers: {", ".join(makers_found)}</div>'

    event_badge = 'BASELINE' if event == 'baseline_stock_found' else 'FEED ENTRY' if event == 'feed_entry' else 'CHANGED'
    return f"""
    <div class="alert-card priority-{priority}">
        <div class="alert-header">
            <span class="priority-badge" style="color:{color}">{label}</span>
            <span class="event-badge">{event_badge}</span>
            <a href="{url}" target="_blank" class="site-name">{source}</a>
            <span class="alert-ts">{ts}</span>
        </div>
        <div class="alert-body">
            {drop_html}
            {notable_html}
            {summary_html}
            {makers_html}
            {matches_html}
        </div>
    </div>"""

def generate_alerts_page():
    alerts = load_recent_alerts(HOURS_BACK)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

    if not alerts:
        alerts_html = '<div class="no-alerts">No alerts in the last 48 hours. All quiet. 🔍</div>'
    else:
        alerts_html = '\n'.join(render_alert_card(a) for a in alerts)

    critical_count = sum(1 for a in alerts if a.get('priority') == 'critical')
    high_count     = sum(1 for a in alerts if a.get('priority') == 'high')
    medium_count   = sum(1 for a in alerts if a.get('priority') == 'medium')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="30">
  <title>Drop Watcher — Alerts</title>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --black: #0a0a0a; --steel: #1c1c1c; --iron: #2a2a2a;
      --ember: #c0392b; --flame: #e67e22; --ash: #888;
      --silver: #d0d0d0; --white: #f0f0f0;
    }}
    body {{ background: var(--black); color: var(--white); font-family: 'Share Tech Mono', monospace; padding: 2rem; }}
    h1 {{ font-family: 'Bebas Neue', sans-serif; font-size: 3rem; color: var(--white); letter-spacing: 0.05em; }}
    h1 span {{ color: var(--ember); }}
    .subtitle {{ color: var(--ash); font-size: 0.75rem; letter-spacing: 0.3em; margin-bottom: 0.5rem; }}
    .flame-line {{ height: 2px; background: linear-gradient(90deg, transparent, var(--ember), var(--flame), var(--ember), transparent); margin: 1rem 0 2rem; }}

    .nav {{ display: flex; gap: 2rem; margin-bottom: 2rem; font-size: 0.75rem; letter-spacing: 0.2em; }}
    .nav a {{ color: var(--ash); text-decoration: none; }}
    .nav a:hover {{ color: var(--flame); }}
    .nav a.active {{ color: var(--flame); border-bottom: 1px solid var(--flame); }}

    .stats {{ display: flex; gap: 2rem; margin-bottom: 2rem; font-size: 0.75rem; }}
    .stat {{ padding: 0.5rem 1rem; border: 1px solid var(--iron); }}
    .stat-label {{ color: var(--ash); font-size: 0.65rem; letter-spacing: 0.2em; }}
    .stat-value {{ font-family: 'Bebas Neue', sans-serif; font-size: 1.5rem; }}

    .alert-card {{ border: 1px solid var(--iron); margin-bottom: 1rem; }}
    .alert-card.priority-critical {{ border-left: 3px solid #e74c3c; }}
    .alert-card.priority-high {{ border-left: 3px solid #e67e22; }}
    .alert-card.priority-medium {{ border-left: 3px solid #f1c40f; }}

    .alert-header {{ display: flex; gap: 1rem; align-items: center; padding: 0.6rem 1rem; background: var(--steel); flex-wrap: wrap; }}
    .priority-badge {{ font-family: 'Bebas Neue', sans-serif; font-size: 1rem; letter-spacing: 0.1em; }}
    .event-badge {{ font-size: 0.6rem; letter-spacing: 0.2em; color: var(--ash); border: 1px solid var(--iron); padding: 0.1rem 0.4rem; }}
    .site-name {{ color: var(--silver); text-decoration: none; font-size: 0.85rem; }}
    .site-name:hover {{ color: var(--flame); }}
    .alert-ts {{ color: var(--ash); font-size: 0.65rem; margin-left: auto; }}

    .alert-body {{ padding: 0.75rem 1rem; font-size: 0.75rem; }}
    .drop-announcement {{ background: rgba(192,57,43,0.15); color: var(--flame); padding: 0.5rem 0.75rem; margin-bottom: 0.5rem; border-left: 2px solid var(--ember); }}
    .timing {{ color: var(--white); margin-left: 1rem; }}
    .confidence {{ color: var(--ash); margin-left: 1rem; font-size: 0.65rem; }}
    .notable-items {{ padding-left: 1.5rem; color: var(--silver); line-height: 1.8; }}
    .notable-items li {{ list-style: '→ '; }}
    .summary {{ color: var(--ash); font-style: italic; margin-top: 0.5rem; font-family: 'Crimson Pro', serif; font-size: 0.85rem; }}
    .makers-found {{ color: var(--ash); font-size: 0.7rem; margin-top: 0.4rem; }}
    .matches {{ color: var(--ash); font-size: 0.7rem; margin-top: 0.4rem; }}

    .no-alerts {{ color: var(--ash); padding: 2rem; text-align: center; border: 1px solid var(--iron); }}

    footer {{ margin-top: 3rem; color: var(--ash); font-size: 0.65rem; letter-spacing: 0.3em; display: flex; justify-content: space-between; }}
    .hgr {{ font-family: 'Bebas Neue', sans-serif; color: var(--ember); font-size: 1.2rem; }}
  </style>
</head>
<body>
  <h1>DROP <span>WATCHER</span></h1>
  <p class="subtitle">LIVE ALERTS — LAST 48 HOURS — AUTO REFRESHES EVERY 30 SECONDS</p>
  <div class="flame-line"></div>

  <nav class="nav">
    <a href="/alerts.html" class="active">ALERTS</a>
    <a href="/status.html">STATUS</a>
    <a href="/index.html">HOME</a>
  </nav>

  <div class="stats">
    <div class="stat">
      <div class="stat-label">TOTAL</div>
      <div class="stat-value" style="color:var(--white)">{len(alerts)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">CRITICAL</div>
      <div class="stat-value" style="color:#e74c3c">{critical_count}</div>
    </div>
    <div class="stat">
      <div class="stat-label">HIGH</div>
      <div class="stat-value" style="color:#e67e22">{high_count}</div>
    </div>
    <div class="stat">
      <div class="stat-label">MEDIUM</div>
      <div class="stat-value" style="color:#f1c40f">{medium_count}</div>
    </div>
    <div class="stat">
      <div class="stat-label">LAST UPDATED</div>
      <div class="stat-value" style="color:var(--ash);font-size:0.8rem;padding-top:0.4rem">{now_str}</div>
    </div>
  </div>

  {alerts_html}

  <footer>
    <span>instockornot.club — simonhg321/drop-watcher</span>
    <span class="hgr">HGR</span>
  </footer>
</body>
</html>"""

    try:
        with open(ALERTS_HTML, 'w') as f:
            f.write(html)
        print(f"✓ Alerts page written — {len(alerts)} alerts in last {HOURS_BACK}h")
    except PermissionError:
        print(f"✗ Cannot write to {ALERTS_HTML} — check permissions")


if __name__ == '__main__':
    generate_alerts_page()
