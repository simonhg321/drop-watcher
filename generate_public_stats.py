#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
generate_public_stats.py
Drop Watcher — Public Stats Page Generator
Cherry-picks aggregate, non-PII data from traffic + security sources.
Outputs to /var/www/html/stats.html (public, no auth).
Cron: */10 * * * *
HGR
"""

import html as html_mod
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import paths

# Import data loaders from existing generators
from generate_traffic import (
    fetch_cloudflare_data, parse_cf_today, parse_cf_daily, parse_cf_hourly,
    load_goaccess_data, parse_goaccess_top_referrers,
    load_watcher_stats, load_api_usage, load_sms_stats,
    fmt_bytes, fmt_num,
)

log = logging.getLogger('public_stats')

PUBLIC_STATS_HTML = os.path.join(paths.WWW_DIR, 'stats.html')


# ── Safe data helpers (no PII) ──────────────────────────────────────────────

def count_ai_calls():
    """Count AI calls by line-counting ai_calls.jsonl. Never loads prompts."""
    total = 0
    today_count = 0
    today_prefix = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if not os.path.exists(paths.AI_CALLS_JSONL):
        return {'total': 0, 'today': 0}

    try:
        with open(paths.AI_CALLS_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                if line[:15].find(today_prefix) >= 0:
                    today_count += 1
    except Exception:
        pass

    return {'total': total, 'today': today_count}


def safe_referrer_domains(ga_refs):
    """Strip referrer URLs to domain-only. No paths, no params."""
    domain_hits = {}
    for ref in ga_refs:
        raw = ref.get('referrer', '').strip()
        if not raw or raw.startswith(' '):
            continue  # skip GoAccess sub-items (indented)
        try:
            parsed = urlparse(raw if '://' in raw else f'https://{raw}')
            domain = parsed.netloc or parsed.path.split('/')[0]
            domain = domain.lower().lstrip('www.')
        except Exception:
            domain = raw
        if domain and domain != 'instockornot.club':
            domain_hits[domain] = domain_hits.get(domain, 0) + ref.get('hits', 0)

    return sorted(domain_hits.items(), key=lambda x: x[1], reverse=True)[:10]


def load_security_counts():
    """Load only aggregate counts from security analysis. No IPs."""
    try:
        from generate_security import analyze_logs
        data = analyze_logs()
        if not data:
            return {'scanners': 0, 'rate_abusers': 0, 'bad_ua_types': 0}
        return {
            'scanners': len(data.get('scanners', {})),
            'rate_abusers': len(data.get('rate_abusers', {})),
            'bad_ua_types': len(data.get('bad_ua_summary', {})),
        }
    except Exception:
        return {'scanners': 0, 'rate_abusers': 0, 'bad_ua_types': 0}


# ── HTML generation ─────────────────────────────────────────────────────────

def generate_page():
    log.info("Generating public stats page...")

    # Fetch all data sources
    cf_data = fetch_cloudflare_data()
    cf_today = parse_cf_today(cf_data)
    cf_daily = parse_cf_daily(cf_data)
    cf_hourly = parse_cf_hourly(cf_data)

    ga_data = load_goaccess_data()
    ga_refs = parse_goaccess_top_referrers(ga_data)

    watcher_stats = load_watcher_stats()
    api_usage = load_api_usage()
    sms_stats = load_sms_stats()
    ai_calls = count_ai_calls()
    security = load_security_counts()

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Section A: Hero stats ───────────────────────────────────────────────
    threats = cf_today.get('threats', 0)
    hero_html = f"""
    <div class="stats-grid hero-grid">
      <div class="stat-card">
        <div class="stat-value" style="color:var(--flame)">{watcher_stats.get('active_watchers', 0)}</div>
        <div class="stat-label">ACTIVE WATCHES</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{fmt_num(watcher_stats.get('drops_total', 0))}</div>
        <div class="stat-label">DROPS DETECTED</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{watcher_stats.get('drops_24h', 0)}</div>
        <div class="stat-label">DROPS TODAY</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{fmt_num(ai_calls['total'])}</div>
        <div class="stat-label">PAGES ANALYZED</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{sms_stats.get('total', 0)}</div>
        <div class="stat-label">SMS ALERTS SENT</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:{('#2ecc71' if threats == 0 else '#e74c3c')}">{threats}</div>
        <div class="stat-label">THREATS BLOCKED</div>
      </div>
    </div>"""

    # ── Section B: 7-day bar chart ──────────────────────────────────────────
    bars_html = ''
    if cf_daily:
        max_uniques = max((d['uniques'] for d in cf_daily), default=1) or 1
        bars = []
        for d in cf_daily:
            pct = int((d['uniques'] / max_uniques) * 100)
            day_label = d['date'][5:]
            bars.append(f"""
              <div class="bar-col">
                <div class="bar-value">{d['uniques']}</div>
                <div class="bar" style="height:{max(pct, 2)}%"></div>
                <div class="bar-label">{day_label}</div>
              </div>""")
        bars_html = f"""
        <div class="section-head">7-DAY VISITORS</div>
        <div class="bar-chart">{''.join(bars)}</div>"""

    # ── 24h hourly chart ────────────────────────────────────────────────────
    hourly_html = ''
    if cf_hourly:
        max_h = max((h['uniques'] for h in cf_hourly), default=1) or 1
        h_bars = []
        for h in cf_hourly:
            pct = int((h['uniques'] / max_h) * 100)
            hr = h['hour'][-2:]
            h_bars.append(f"""
              <div class="bar-col bar-col-sm">
                <div class="bar bar-sm" style="height:{max(pct, 2)}%"></div>
                <div class="bar-label">{hr}</div>
              </div>""")
        hourly_html = f"""
        <div class="section-head">LAST 24 HOURS</div>
        <div class="bar-chart bar-chart-hourly">{''.join(h_bars)}</div>"""

    # ── Section C: Today snapshot ───────────────────────────────────────────
    uniques = cf_today.get('uniques', 0)
    requests = cf_today.get('requests', 0)
    bandwidth = cf_today.get('bytes', 0)
    countries = cf_today.get('countries', [])

    snapshot_html = f"""
    <div class="section-head">TODAY</div>
    <div class="stats-grid snap-grid">
      <div class="stat-card">
        <div class="stat-value">{fmt_num(uniques)}</div>
        <div class="stat-label">UNIQUE VISITORS</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{fmt_num(requests)}</div>
        <div class="stat-label">REQUESTS</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{fmt_bytes(bandwidth)}</div>
        <div class="stat-label">BANDWIDTH</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{len(countries)}</div>
        <div class="stat-label">COUNTRIES</div>
      </div>
    </div>"""

    # ── Section D: Countries + Referrers ────────────────────────────────────
    country_rows = ''
    for c in countries[:10]:
        name = html_mod.escape(c.get('clientCountryName', '?'))
        count = c.get('requests', 0)
        country_rows += f'<tr><td>{name}</td><td class="num-cell">{count}</td></tr>'
    if not country_rows:
        country_rows = '<tr><td colspan="2" class="empty-cell">No data yet</td></tr>'

    safe_refs = safe_referrer_domains(ga_refs)
    ref_rows = ''
    for domain, hits in safe_refs:
        ref_rows += f'<tr><td>{html_mod.escape(domain)}</td><td class="num-cell">{hits}</td></tr>'
    if not ref_rows:
        ref_rows = '<tr><td colspan="2" class="empty-cell">No referrers yet</td></tr>'

    panels_html = f"""
    <div class="section-head">WHERE THEY COME FROM</div>
    <div class="panels">
      <div class="panel">
        <div class="panel-title">TOP COUNTRIES</div>
        <div class="panel-body">
          <table class="data-table">
            <thead><tr><th>COUNTRY</th><th>REQUESTS</th></tr></thead>
            <tbody>{country_rows}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-title">TOP REFERRERS</div>
        <div class="panel-body">
          <table class="data-table">
            <thead><tr><th>SOURCE</th><th>HITS</th></tr></thead>
            <tbody>{ref_rows}</tbody>
          </table>
        </div>
      </div>
    </div>"""

    # ── Section E: AI & Cost ────────────────────────────────────────────────
    ai_html = f"""
    <div class="section-head">BEHIND THE SCENES</div>
    <div class="stats-grid tri-grid">
      <div class="stat-card">
        <div class="stat-value">{ai_calls['today']}</div>
        <div class="stat-label">AI CALLS TODAY</div>
        <div class="stat-sub">{fmt_num(ai_calls['total'])} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${api_usage.get('cost_24h', 0):.2f}</div>
        <div class="stat-label">API COST TODAY</div>
        <div class="stat-sub">${api_usage.get('total_cost', 0):.2f} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{sms_stats.get('last_24h', 0)}</div>
        <div class="stat-label">SMS ALERTS TODAY</div>
        <div class="stat-sub">{sms_stats.get('total', 0)} total</div>
      </div>
    </div>"""

    # ── Section F: Security ─────────────────────────────────────────────────
    total_threats = security['scanners'] + security['rate_abusers']
    sec_html = f"""
    <div class="section-head">SECURITY</div>
    <div class="stats-grid tri-grid">
      <div class="stat-card">
        <div class="stat-value" style="color:{('#2ecc71' if total_threats == 0 else '#e74c3c')}">{total_threats}</div>
        <div class="stat-label">THREATS DETECTED</div>
        <div class="stat-sub">last 24h</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{security['scanners']}</div>
        <div class="stat-label">SCANNERS BLOCKED</div>
        <div class="stat-sub">unique IPs</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{security['bad_ua_types']}</div>
        <div class="stat-label">BAD BOT TYPES</div>
        <div class="stat-sub">patterns matched</div>
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
  <title>Live Stats — Drop Watcher</title>
  <meta name="description" content="Live stats from Drop Watcher — active watches, drops detected, AI pages analyzed, traffic, and security.">
  <meta property="og:title" content="Drop Watcher — Live Stats">
  <meta property="og:description" content="Real-time platform stats. You Sleep. We Watch. You Score.">
  <meta property="og:image" content="https://instockornot.club/og-image.jpg">
  <meta property="og:url" content="https://instockornot.club/stats.html">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="canonical" href="https://instockornot.club/stats.html">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --black: #0a0a0a; --steel: #1c1c1c; --iron: #2a2a2a;
      --ember: #c0392b; --flame: #e67e22; --ash: #888;
      --silver: #d0d0d0; --white: #f0f0f0;
    }}
    body {{ background: var(--black); color: var(--white); font-family: 'Share Tech Mono', monospace; padding: 1rem; max-width: 960px; margin: 0 auto; }}
    h1 {{ font-family: 'Bebas Neue', sans-serif; font-size: clamp(2rem, 8vw, 3rem); color: var(--white); letter-spacing: 0.05em; }}
    h1 span {{ color: var(--ember); }}
    .subtitle {{ color: var(--ash); font-size: 0.7rem; letter-spacing: 0.2em; margin-bottom: 1rem; line-height: 1.6; }}
    .flame-line {{ height: 2px; background: linear-gradient(90deg, transparent, var(--ember), var(--flame), var(--ember), transparent); margin: 1rem 0 1.5rem; }}

    /* Nav */
    .nav {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; font-size: 0.75rem; letter-spacing: 0.2em; flex-wrap: wrap; }}
    .nav a {{ color: var(--ash); text-decoration: none; }}
    .nav a:hover {{ color: var(--flame); }}
    .nav a.active {{ color: var(--flame); border-bottom: 1px solid var(--flame); }}

    /* Stats grid */
    .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--iron); border: 1px solid var(--iron); margin-bottom: 2rem; }}
    .stat-card {{ background: var(--black); padding: 1.2rem 0.5rem; text-align: center; }}
    .stat-label {{ font-size: 0.55rem; letter-spacing: 0.15em; color: var(--ash); margin-top: 0.3rem; }}
    .stat-value {{ font-family: 'Bebas Neue', sans-serif; font-size: clamp(1.4rem, 5vw, 2rem); color: var(--white); }}
    .stat-sub {{ font-size: 0.55rem; color: var(--ash); margin-top: 0.2rem; }}

    /* Section heads */
    .section-head {{ font-family: 'Bebas Neue', sans-serif; font-size: 1.3rem; letter-spacing: 0.1em; color: var(--ash); margin: 2rem 0 1rem; }}

    /* Bar chart */
    .bar-chart {{ display: flex; align-items: flex-end; gap: 2px; height: 120px; border-bottom: 1px solid var(--iron); padding-bottom: 4px; margin-bottom: 2rem; overflow: hidden; }}
    .bar-chart-hourly {{ height: 80px; }}
    .bar-col {{ display: flex; flex-direction: column; align-items: center; flex: 1; min-width: 0; height: 100%; justify-content: flex-end; }}
    .bar-col-sm {{ min-width: 0; }}
    .bar {{ background: linear-gradient(to top, var(--ember), var(--flame)); width: 100%; min-height: 2px; transition: height 0.3s; }}
    .bar-sm {{ width: 80%; }}
    .bar-value {{ font-size: 0.55rem; color: var(--silver); margin-bottom: 4px; white-space: nowrap; }}
    .bar-label {{ font-size: 0.5rem; color: var(--ash); margin-top: 4px; white-space: nowrap; }}

    /* Panels grid */
    .panels {{ display: grid; grid-template-columns: 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
    .panel {{ border: 1px solid var(--iron); overflow-x: auto; }}
    .panel-title {{ font-family: 'Bebas Neue', sans-serif; font-size: 1rem; letter-spacing: 0.1em; color: var(--ember); padding: 0.75rem 1rem; background: var(--steel); border-bottom: 1px solid var(--iron); }}
    .panel-body {{ padding: 0; }}

    /* Data tables */
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.7rem; }}
    .data-table th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--ash); font-size: 0.6rem; letter-spacing: 0.15em; border-bottom: 1px solid var(--iron); white-space: nowrap; }}
    .data-table td {{ padding: 0.4rem 0.75rem; border-bottom: 1px solid rgba(42,42,42,0.5); color: var(--silver); }}
    .data-table tr:last-child td {{ border-bottom: none; }}
    .data-table tr:hover td {{ background: var(--steel); }}
    .num-cell {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .empty-cell {{ color: var(--ash); text-align: center; padding: 1rem !important; }}

    /* Desktop */
    @media (min-width: 700px) {{
      .hero-grid {{ grid-template-columns: repeat(6, 1fr); }}
      .snap-grid {{ grid-template-columns: repeat(4, 1fr); }}
      .tri-grid {{ grid-template-columns: repeat(3, 1fr); }}
      .panels {{ grid-template-columns: repeat(2, 1fr); }}
    }}

    /* Footer */
    footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--iron); color: var(--ash); font-size: 0.6rem; letter-spacing: 0.15em; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; }}
    footer a {{ color: var(--ash); text-decoration: none; }}
    footer a:hover {{ color: var(--flame); }}
    .hgr {{ font-family: 'Bebas Neue', sans-serif; color: var(--ember); font-size: 1.2rem; }}
  </style>
</head>
<body>
  <h1>LIVE <span>STATS</span></h1>
  <p class="subtitle">WHAT DROP WATCHER IS DOING RIGHT NOW</p>
  <div class="flame-line"></div>

  <nav class="nav">
    <a href="/">HOME</a>
    <a href="/watchlist.html">WATCH SOMETHING</a>
    <a href="/alerts.html">ALERTS</a>
    <a href="/what-we-watch.html">WHAT WE WATCH</a>
    <a href="/stats.html" class="active">STATS</a>
  </nav>

  {hero_html}

  {bars_html}

  {hourly_html}

  {snapshot_html}

  {panels_html}

  {ai_html}

  {sec_html}

  <footer>
    <div>UPDATED {now_str} — AUTO-REFRESHES EVERY 2 MIN</div>
    <a href="/">INSTOCKORNOT.CLUB</a>
    <div class="hgr">HGR</div>
  </footer>
</body>
</html>"""

    os.makedirs(os.path.dirname(PUBLIC_STATS_HTML), exist_ok=True)
    with open(PUBLIC_STATS_HTML, 'w') as f:
        f.write(html)
    log.info(f"Public stats page written to {PUBLIC_STATS_HTML}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    generate_page()


if __name__ == '__main__':
    main()
