#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
generate_simon_status.py
Drop Watcher — Simon's Deep Dive Status Page
Everything: watches, keywords, AI calls, drops, SMS, visitor journeys.
PII-heavy — lives under /stats/ behind basic auth.
Cron: */10 * * * *
HGR
"""

import html as html_mod
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import paths
import db as _db
from generate_traffic import (
    fetch_cloudflare_data, parse_cf_today,
    load_watcher_stats, load_api_usage, load_sms_stats,
    load_ai_calls, load_pageviews,
    fmt_bytes, fmt_num,
)

log = logging.getLogger('simon_status')

SIMON_HTML = os.path.join(paths.WWW_DIR, 'stats', 'simon.html')


# ── Data loaders ────────────────────────────────────────────────────────────

def load_all_watchers():
    """Load full watcher list from SQLite."""
    return _db.get_all_watchers()


def load_recent_drops(limit=30):
    """Load last N drops from SQLite."""
    drops = _db.get_recent_drops(hours=72)  # get last 3 days, then limit
    return drops[:limit]


def load_recent_alerts(limit=20):
    """Load last N sent alerts from SQLite."""
    return _db.get_recent_alerts_sent(limit=limit)


# ── HTML generation ─────────────────────────────────────────────────────────

def generate_page():
    log.info("Generating Simon status page...")

    watchers = load_all_watchers()
    active = [w for w in watchers if w.get('active')]
    pending = [w for w in watchers if not w.get('active')]

    ai_calls = load_ai_calls(limit=30)
    drops = load_recent_drops(limit=30)
    alerts = load_recent_alerts(limit=20)
    api_usage = load_api_usage()
    sms_stats = load_sms_stats()
    pageviews = load_pageviews()

    cf_data = fetch_cloudflare_data()
    cf_today = parse_cf_today(cf_data)

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Hero stats ──────────────────────────────────────────────────────────
    unique_emails = len(set(w.get('email', '').lower() for w in watchers))
    sms_ready = sum(1 for w in active if w.get('sms_approved'))

    hero_html = f"""
    <div class="stats-grid hero-grid">
      <div class="stat-card">
        <div class="stat-value" style="color:var(--flame)">{len(active)}</div>
        <div class="stat-label">ACTIVE WATCHES</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{len(pending)}</div>
        <div class="stat-label">PENDING</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{unique_emails}</div>
        <div class="stat-label">UNIQUE EMAILS</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{sms_ready}</div>
        <div class="stat-label">SMS READY</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${api_usage.get('cost_24h', 0):.2f}</div>
        <div class="stat-label">API COST 24H</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${api_usage.get('total_cost', 0):.2f}</div>
        <div class="stat-label">API COST TOTAL</div>
      </div>
    </div>"""

    # ── Active watches table ────────────────────────────────────────────────
    watch_rows = ''
    for w in sorted(active, key=lambda x: x.get('created', ''), reverse=True):
        email = html_mod.escape(w.get('email', '?'))
        url = html_mod.escape(w.get('url', '?'))
        domain = url.split('/')[2] if url.count('/') >= 2 else url
        kw = html_mod.escape(w.get('keywords', '?'))
        pri = w.get('priority', 'medium')
        pri_color = {'critical': '#e74c3c', 'high': '#e67e22', 'medium': '#f1c40f'}.get(pri, 'var(--ash)')
        phone = '📱' if w.get('sms_approved') else ''
        created = w.get('created', '?')[:10]
        watch_rows += f'''<tr>
          <td>{email}</td>
          <td class="path-cell" title="{url}">{domain}</td>
          <td class="kw-cell">{kw}</td>
          <td style="color:{pri_color};text-transform:uppercase;font-size:0.6rem">{pri}</td>
          <td>{phone}</td>
          <td style="color:var(--ash)">{created}</td>
        </tr>'''

    watches_html = f"""
    <div class="section-head">ACTIVE WATCHES <span class="badge">{len(active)}</span></div>
    <div class="panel">
      <div class="panel-body" style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>EMAIL</th><th>SITE</th><th>KEYWORDS</th><th>PRI</th><th>SMS</th><th>SINCE</th></tr></thead>
          <tbody>{watch_rows}</tbody>
        </table>
      </div>
    </div>"""

    # ── AI calls table ──────────────────────────────────────────────────────
    ai_rows = ''
    for c in reversed(ai_calls):
        ts = c.get('ts', '?')[:16].replace('T', ' ')
        caller = c.get('caller', '?').replace('analyze_', '')
        site = html_mod.escape(c.get('site', '?'))[:30]
        resp = c.get('response', {})
        alert = '🔔' if resp.get('alert_worthy') else ''
        pri = resp.get('priority', '?')
        pri_color = {'critical': '#e74c3c', 'high': '#e67e22', 'medium': '#f1c40f', 'low': 'var(--ash)'}.get(pri, 'var(--ash)')
        kw_found = html_mod.escape(', '.join(resp.get('keywords_found') or [])[:40])
        summary = html_mod.escape(resp.get('page_summary', ''))[:120]
        notable = resp.get('notable_items', [])
        notable_str = html_mod.escape(', '.join(notable[:3]))[:100] if notable else ''

        ai_rows += f'''<tr>
          <td style="white-space:nowrap">{ts}</td>
          <td>{caller}</td>
          <td>{site}</td>
          <td>{alert}</td>
          <td style="color:{pri_color}">{pri}</td>
          <td style="color:var(--flame)">{kw_found or '—'}</td>
          <td class="path-cell">{summary}</td>
        </tr>'''
        if notable_str:
            ai_rows += f'''<tr>
              <td colspan="7" style="padding:0.2rem 0.75rem 0.6rem 2rem;color:var(--flame);font-size:0.6rem;border-bottom:1px solid var(--iron)">{notable_str}</td>
            </tr>'''

    ai_html = f"""
    <div class="section-head">AI CALLS (LAST 30)</div>
    <div class="panel">
      <div class="panel-body" style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>TIME</th><th>TYPE</th><th>SITE</th><th></th><th>PRI</th><th>FOUND</th><th>SUMMARY</th></tr></thead>
          <tbody>{ai_rows}</tbody>
        </table>
      </div>
    </div>"""

    # ── Recent drops table ──────────────────────────────────────────────────
    drop_rows = ''
    for d in reversed(drops):
        ts = d.get('timestamp', '?')[:16].replace('T', ' ')
        source = html_mod.escape(d.get('source', '?'))[:30]
        pri = d.get('priority', '?')
        pri_color = {'critical': '#e74c3c', 'high': '#e67e22', 'medium': '#f1c40f', 'low': 'var(--ash)'}.get(pri, 'var(--ash)')
        summary = html_mod.escape(d.get('page_summary', ''))[:100]
        notable = d.get('notable_items', [])
        items = html_mod.escape(', '.join(notable[:3]))[:80] if notable else '—'
        event = d.get('event', '?')

        drop_rows += f'''<tr>
          <td style="white-space:nowrap">{ts}</td>
          <td>{source}</td>
          <td style="color:{pri_color}">{pri}</td>
          <td style="font-size:0.6rem">{event}</td>
          <td class="path-cell" style="color:var(--flame)">{items}</td>
        </tr>'''

    drops_html = f"""
    <div class="section-head">RECENT DROPS <span class="badge">{len(drops)}</span></div>
    <div class="panel">
      <div class="panel-body" style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>TIME</th><th>SOURCE</th><th>PRI</th><th>EVENT</th><th>ITEMS</th></tr></thead>
          <tbody>{drop_rows}</tbody>
        </table>
      </div>
    </div>"""

    # ── SMS log ─────────────────────────────────────────────────────────────
    sms_rows = ''
    for entry in reversed(sms_stats.get('recent', [])):
        sent_at = entry.get('sent_at', '?')[:16].replace('T', ' ')
        phone = html_mod.escape(str(entry.get('phone', '?')))
        alert_id = html_mod.escape(str(entry.get('alert_id', '—')))[:50]
        sms_rows += f'<tr><td>{sent_at}</td><td>{phone}</td><td class="path-cell">{alert_id}</td></tr>'

    sms_html = ''
    if sms_stats.get('total', 0) > 0:
        sms_html = f"""
    <div class="section-head">SMS LOG <span class="badge">{sms_stats['total']}</span></div>
    <div class="panel">
      <div class="panel-body">
        <table class="data-table">
          <thead><tr><th>SENT</th><th>TO</th><th>ALERT</th></tr></thead>
          <tbody>{sms_rows}</tbody>
        </table>
      </div>
    </div>"""

    # ── Visitor journeys (24h) ──────────────────────────────────────────────
    journey_rows = ''
    sorted_journeys = sorted(pageviews['journeys'].items(), key=lambda x: len(x[1]), reverse=True)[:15]
    for vid, hits in sorted_journeys:
        pages = ' → '.join(h['path'] for h in sorted(hits, key=lambda x: x['ts']))
        first_ref = next((h['ref'] for h in hits if h['ref'] and 'instockornot.club' not in h['ref']), '—')
        if len(first_ref) > 50:
            first_ref = first_ref[:50] + '…'
        journey_rows += f'''<tr>
          <td style="color:var(--flame)">{html_mod.escape(vid[:12])}</td>
          <td class="num-cell">{len(hits)}</td>
          <td class="path-cell" style="max-width:400px">{html_mod.escape(pages)}</td>
          <td>{html_mod.escape(first_ref)}</td>
        </tr>'''

    unique_24h = len(pageviews['vids_24h'])
    visitor_html = f"""
    <div class="section-head">VISITOR JOURNEYS (24H) <span class="badge">{unique_24h} visitors</span></div>
    <div class="panel">
      <div class="panel-body" style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>VID</th><th>HITS</th><th>JOURNEY</th><th>CAME FROM</th></tr></thead>
          <tbody>{journey_rows}</tbody>
        </table>
      </div>
    </div>"""

    # ── Alerts sent log ─────────────────────────────────────────────────────
    alert_rows = ''
    for a in reversed(alerts):
        ts = a.get('sent_at', a.get('ts', '?'))[:16].replace('T', ' ')
        to = html_mod.escape(a.get('email', a.get('to', '?')))
        source = html_mod.escape(str(a.get('source', a.get('site', '?'))))[:30]
        subj = html_mod.escape(str(a.get('subject', a.get('alert_id', '?'))))[:60]
        alert_rows += f'<tr><td>{ts}</td><td>{to}</td><td>{source}</td><td class="path-cell">{subj}</td></tr>'

    alerts_html = ''
    if alerts:
        alerts_html = f"""
    <div class="section-head">ALERTS SENT (LAST 20)</div>
    <div class="panel">
      <div class="panel-body" style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>SENT</th><th>TO</th><th>SOURCE</th><th>SUBJECT</th></tr></thead>
          <tbody>{alert_rows}</tbody>
        </table>
      </div>
    </div>"""

    # ── Full page ───────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="120">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>Simon Status — Drop Watcher</title>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --black: #0a0a0a; --steel: #1c1c1c; --iron: #2a2a2a;
      --ember: #c0392b; --flame: #e67e22; --ash: #888;
      --silver: #d0d0d0; --white: #f0f0f0;
    }}
    body {{ background: var(--black); color: var(--white); font-family: 'Share Tech Mono', monospace; padding: 1rem; }}
    h1 {{ font-family: 'Bebas Neue', sans-serif; font-size: clamp(2rem, 8vw, 3rem); color: var(--white); letter-spacing: 0.05em; }}
    h1 span {{ color: var(--ember); }}
    .subtitle {{ color: var(--ash); font-size: 0.7rem; letter-spacing: 0.2em; margin-bottom: 1rem; line-height: 1.6; }}
    .flame-line {{ height: 2px; background: linear-gradient(90deg, transparent, var(--ember), var(--flame), var(--ember), transparent); margin: 1rem 0 1.5rem; }}

    .nav {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; font-size: 0.75rem; letter-spacing: 0.2em; flex-wrap: wrap; }}
    .nav a {{ color: var(--ash); text-decoration: none; }}
    .nav a:hover {{ color: var(--flame); }}
    .nav a.active {{ color: var(--flame); border-bottom: 1px solid var(--flame); }}

    .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--iron); border: 1px solid var(--iron); margin-bottom: 2rem; }}
    .stat-card {{ background: var(--black); padding: 1.2rem 0.5rem; text-align: center; }}
    .stat-label {{ font-size: 0.55rem; letter-spacing: 0.15em; color: var(--ash); margin-top: 0.3rem; }}
    .stat-value {{ font-family: 'Bebas Neue', sans-serif; font-size: clamp(1.4rem, 5vw, 2rem); color: var(--white); }}
    .stat-sub {{ font-size: 0.55rem; color: var(--ash); margin-top: 0.2rem; }}

    .section-head {{ font-family: 'Bebas Neue', sans-serif; font-size: 1.3rem; letter-spacing: 0.1em; color: var(--ash); margin: 2rem 0 1rem; }}
    .section-head .badge {{ font-size: 0.8rem; color: var(--flame); margin-left: 0.5rem; }}

    .panel {{ border: 1px solid var(--iron); margin-bottom: 2rem; overflow-x: auto; }}
    .panel-body {{ padding: 0; }}

    .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.65rem; }}
    .data-table th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--ash); font-size: 0.55rem; letter-spacing: 0.15em; border-bottom: 1px solid var(--iron); white-space: nowrap; position: sticky; top: 0; background: var(--steel); }}
    .data-table td {{ padding: 0.35rem 0.75rem; border-bottom: 1px solid rgba(42,42,42,0.5); color: var(--silver); }}
    .data-table tr:last-child td {{ border-bottom: none; }}
    .data-table tr:hover td {{ background: var(--steel); }}
    .num-cell {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .path-cell {{ max-width: 55vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .kw-cell {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--flame); }}

    @media (min-width: 700px) {{
      .hero-grid {{ grid-template-columns: repeat(6, 1fr); }}
      .path-cell {{ max-width: 350px; }}
      .kw-cell {{ max-width: 250px; }}
    }}

    footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--iron); color: var(--ash); font-size: 0.6rem; letter-spacing: 0.15em; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; }}
    .hgr {{ font-family: 'Bebas Neue', sans-serif; color: var(--ember); font-size: 1.2rem; }}
  </style>
</head>
<body>
  <h1>SIMON <span>STATUS</span></h1>
  <p class="subtitle">EVERYTHING — EYES ONLY</p>
  <div class="flame-line"></div>

  <nav class="nav">
    <a href="/stats/dashboard.html">DASHBOARD</a>
    <a href="/stats/simon.html" class="active">DEEP DIVE</a>
    <a href="/stats/traffic.html">TRAFFIC</a>
    <a href="/stats/security.html">SECURITY</a>
    <a href="/stats/status.html">STATUS</a>
    <a href="/alerts.html">ALERTS</a>
    <a href="/">HOME</a>
  </nav>

  {hero_html}

  {watches_html}

  {ai_html}

  {drops_html}

  {sms_html}

  {alerts_html}

  {visitor_html}

  <footer>
    <div>UPDATED {now_str} — AUTO-REFRESHES EVERY 2 MIN</div>
    <div class="hgr">HGR</div>
  </footer>
</body>
</html>"""

    os.makedirs(os.path.dirname(SIMON_HTML), exist_ok=True)
    paths.write_atomic(SIMON_HTML, html)
    log.info(f"Simon status page written to {SIMON_HTML}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    generate_page()


if __name__ == '__main__':
    main()
