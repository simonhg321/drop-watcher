#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
generate_dashboard.py
Drop Watcher — Admin Dashboard Generator
Server-side generation — no client-side API secrets.
Behind .htaccess basic auth at /stats/dashboard.html.
Cron: */10 * * * *
HGR
"""

import html as html_mod
import os
from datetime import datetime, timezone

import paths
import db as _db

DASHBOARD_HTML = os.path.join(paths.WWW_DIR, 'stats', 'dashboard.html')


def generate_dashboard():
    watchers = _db.get_all_watchers()
    active = [w for w in watchers if w.get('active')]
    pending = [w for w in watchers if not w.get('active')]
    unique_emails = len(set(w.get('email', '').lower() for w in watchers))
    sms_count = sum(1 for w in watchers if w.get('phone') and w.get('sms_approved'))

    drops_24h = _db.get_drops_count(hours=24)
    drops_total = _db.get_drops_count()
    by_priority = _db.get_drops_by_priority(hours=24)
    latest_ts = _db.get_latest_drop_timestamp()

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    # Sort: active first, then by created desc
    sorted_watchers = sorted(watchers, key=lambda w: (
        0 if w.get('active') else 1,
        w.get('created', '') or '',
    ))
    sorted_watchers = sorted(sorted_watchers, key=lambda w: (
        0 if w.get('active') else 1,
    ))
    # Within each group, newest first
    active_sorted = sorted(active, key=lambda w: w.get('created', ''), reverse=True)
    pending_sorted = sorted(pending, key=lambda w: w.get('created', ''), reverse=True)
    sorted_watchers = active_sorted + pending_sorted

    # Build watcher rows
    watcher_rows = ''
    for w in sorted_watchers:
        status = '<span class="badge badge-active">Active</span>' if w.get('active') else '<span class="badge badge-pending">Pending</span>'
        email = html_mod.escape(w.get('email', ''))
        name = html_mod.escape(w.get('name', '') or '—')
        raw_url = w.get('url', '') or ''
        url = html_mod.escape(raw_url)
        # derive from the RAW url — deriving from the escaped one double-escapes
        domain = raw_url.replace('https://', '').replace('http://', '').split('/')[0]
        if domain.startswith('www.'):
            domain = domain[4:]
        kw = html_mod.escape(w.get('keywords', ''))
        pri = w.get('priority', 'medium')
        pri_cls = {'critical': 'badge-critical', 'high': 'badge-high', 'medium': 'badge-medium', 'low': 'badge-low'}.get(pri, 'badge-low')
        alert_count = w.get('alert_count', 0)
        phone = '&#x2713;' if w.get('phone') else ''
        created = w.get('created', '')[:16].replace('T', ' ') if w.get('created') else '—'

        watcher_rows += f"""<tr>
          <td>{status}</td>
          <td>{email}</td>
          <td>{name}</td>
          <td class="url-cell" title="{url}"><a href="{url}" target="_blank" style="color:var(--flame)">{html_mod.escape(domain)}</a></td>
          <td class="kw-cell" title="{kw}">{kw}</td>
          <td><span class="badge {pri_cls}">{pri}</span></td>
          <td>{alert_count}</td>
          <td>{phone}</td>
          <td>{created}</td>
        </tr>"""

    if not watcher_rows:
        watcher_rows = '<tr><td colspan="9" class="loading">No watchers yet</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="600">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>Drop Watcher — Admin Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --black: #0a0a0a; --steel: #1c1c1c; --iron: #2a2a2a;
      --ember: #c0392b; --flame: #e67e22; --ash: #888;
      --silver: #d0d0d0; --white: #f0f0f0; --green: #2ecc71; --yellow: #f1c40f;
    }}
    body {{ background: var(--black); color: var(--white); font-family: 'Share Tech Mono', monospace; min-height: 100vh; }}
    .dw-nav {{ border-bottom: 1px solid rgba(255,255,255,0.08); padding: 16px 32px; display: flex; align-items: center; gap: 32px; }}
    .dw-nav .logo {{ font-size: 18px; font-weight: 700; color: var(--white); text-decoration: none; letter-spacing: 0.05em; }}
    .dw-nav .logo span {{ color: var(--ember); }}
    .dw-nav a:not(.logo) {{ font-size: 12px; text-decoration: none; color: var(--ash); letter-spacing: 0.08em; text-transform: uppercase; }}
    .dw-nav a:not(.logo):hover {{ color: var(--white); }}
    .content {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
    h1 {{ font-family: 'Bebas Neue', sans-serif; font-size: 48px; letter-spacing: 0.05em; margin-bottom: 8px; }}
    .subtitle {{ color: var(--ash); font-size: 12px; letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 32px; }}
    .stats-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1px; background: var(--iron); border: 1px solid var(--iron); margin-bottom: 32px;
    }}
    .stat-card {{ background: var(--black); padding: 20px; text-align: center; }}
    .stat-label {{ font-size: 10px; letter-spacing: 0.3em; color: var(--ash); text-transform: uppercase; margin-bottom: 8px; }}
    .stat-value {{ font-family: 'Bebas Neue', sans-serif; font-size: 42px; color: var(--white); }}
    .stat-value.green {{ color: var(--green); }}
    .stat-value.ember {{ color: var(--ember); }}
    .stat-value.flame {{ color: var(--flame); }}
    .stat-value.yellow {{ color: var(--yellow); }}
    .section-title {{
      font-family: 'Bebas Neue', sans-serif; font-size: 28px; letter-spacing: 0.05em;
      color: var(--flame); margin: 40px 0 16px;
    }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--iron); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th {{
      background: var(--steel); padding: 10px 12px; text-align: left;
      font-size: 10px; letter-spacing: 0.2em; color: var(--ember); text-transform: uppercase;
      position: sticky; top: 0;
    }}
    td {{
      padding: 8px 12px; border-bottom: 1px solid var(--iron);
      color: var(--silver); font-size: 11px;
    }}
    tr:hover td {{ background: var(--steel); }}
    .badge {{ display: inline-block; padding: 2px 8px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; }}
    .badge-active {{ background: var(--green); color: #000; }}
    .badge-pending {{ background: var(--ash); color: #000; }}
    .badge-critical {{ background: var(--ember); color: #fff; }}
    .badge-high {{ background: var(--flame); color: #000; }}
    .badge-medium {{ background: var(--yellow); color: #000; }}
    .badge-low {{ background: var(--iron); color: var(--ash); }}
    .url-cell {{ max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .kw-cell {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .generated {{ color: var(--ash); font-size: 11px; margin-bottom: 24px; }}
    .loading {{ color: var(--ash); font-size: 13px; padding: 20px; }}
    footer {{
      margin-top: 48px; border-top: 1px solid var(--iron); padding: 2rem 32px;
      display: flex; justify-content: space-between; align-items: center;
      font-size: 0.65rem; letter-spacing: 0.3em; color: var(--ash); text-transform: uppercase;
    }}
    .footer-hgr {{ color: var(--ember); font-family: 'Bebas Neue', sans-serif; font-size: 1.2rem; letter-spacing: 0.3em; }}
  </style>
</head>
<body>

<nav class="dw-nav">
  <a href="/" class="logo">DROP <span>WATCHER</span></a>
  <a href="/stats/dashboard.html">Dashboard</a>
  <a href="/alerts.html">Alerts</a>
  <a href="/stats/status.html">Status</a>
  <a href="/stats/traffic.html">Traffic</a>
  <a href="/stats/">Server Stats</a>
</nav>

<div class="content">

  <h1>ADMIN DASHBOARD</h1>
  <p class="subtitle">HGR eyes only</p>
  <p class="generated">Generated {now_str} — auto-refreshes every 10 minutes</p>

  <div class="stats-grid">
    <div class="stat-card"><div class="stat-label">Total Watches</div><div class="stat-value">{len(watchers)}</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value green">{len(active)}</div></div>
    <div class="stat-card"><div class="stat-label">Pending</div><div class="stat-value yellow">{len(pending)}</div></div>
    <div class="stat-card"><div class="stat-label">Unique Emails</div><div class="stat-value flame">{unique_emails}</div></div>
    <div class="stat-card"><div class="stat-label">Drops (24h)</div><div class="stat-value ember">{drops_24h}</div></div>
    <div class="stat-card"><div class="stat-label">Critical (24h)</div><div class="stat-value ember">{by_priority.get('critical', 0)}</div></div>
    <div class="stat-card"><div class="stat-label">Total Drops</div><div class="stat-value">{drops_total}</div></div>
    <div class="stat-card"><div class="stat-label">SMS Ready</div><div class="stat-value">{sms_count}</div></div>
  </div>

  <h2 class="section-title">Watchers</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Email</th>
          <th>Name</th>
          <th>URL</th>
          <th>Keywords</th>
          <th>Priority</th>
          <th>Alerts</th>
          <th>Phone</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {watcher_rows}
      </tbody>
    </table>
  </div>

</div>

<footer>
  <span>instockornot.club — Admin</span>
  <span class="footer-hgr">HGR</span>
</footer>

</body>
</html>"""

    os.makedirs(os.path.dirname(DASHBOARD_HTML), exist_ok=True)
    paths.write_atomic(DASHBOARD_HTML, html)
    print(f"Dashboard written — {len(watchers)} watchers, {drops_total} drops")


if __name__ == '__main__':
    generate_dashboard()
