#!/usr/bin/env python3
"""
generate_traffic.py
Drop Watcher — Traffic Dashboard Generator
Pulls Cloudflare analytics + GoAccess data + watcher stats into one admin page.
Run via cron every 10 minutes.
HGR
"""

import html as html_mod
import json
import os
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv

import paths
from collections import defaultdict

load_dotenv(paths.ENV_FILE, override=True)

# Haiku pricing per 1M tokens
INPUT_COST_PER_M  = 0.80
OUTPUT_COST_PER_M = 4.00

# ── Cloudflare config ────────────────────────────────────────────────────────
CF_API_TOKEN = os.environ.get('CF_API_TOKEN')
CF_ZONE_ID = os.environ.get('CF_ZONE_ID')
CF_GRAPHQL_URL = 'https://api.cloudflare.com/client/v4/graphql'

TRAFFIC_HTML = paths.TRAFFIC_HTML
GOACCESS_JSON = paths.GOACCESS_JSON


# ── Cloudflare GraphQL ───────────────────────────────────────────────────────

def fetch_cloudflare_data():
    """Fetch analytics from Cloudflare GraphQL API. Returns dict or None."""
    if not CF_API_TOKEN or not CF_ZONE_ID:
        return None

    now = datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    seven_days_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    twenty_four_h_ago = (now - timedelta(hours=24)).isoformat()

    query = """
    {
      viewer {
        zones(filter: {zoneTag: "%s"}) {
          daily: httpRequests1dGroups(limit: 7, orderBy: [date_ASC], filter: {date_geq: "%s", date_leq: "%s"}) {
            dimensions { date }
            sum { requests pageViews bytes threats }
            uniq { uniques }
          }
          hourly: httpRequests1hGroups(limit: 24, orderBy: [datetime_ASC], filter: {datetime_geq: "%s"}) {
            dimensions { datetime }
            sum { requests pageViews }
            uniq { uniques }
          }
          today: httpRequests1dGroups(limit: 1, filter: {date_geq: "%s", date_leq: "%s"}) {
            sum {
              requests
              pageViews
              bytes
              threats
              countryMap { clientCountryName requests }
              responseStatusMap { edgeResponseStatus requests }
            }
            uniq { uniques }
          }
        }
      }
    }
    """ % (CF_ZONE_ID, seven_days_ago, today, twenty_four_h_ago, today, today)

    try:
        r = httpx.post(
            CF_GRAPHQL_URL,
            headers={
                'Authorization': f'Bearer {CF_API_TOKEN}',
                'Content-Type': 'application/json',
            },
            json={'query': query},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data.get('errors'):
            print(f"Cloudflare API errors: {data['errors']}")
            return None
        zones = data.get('data', {}).get('viewer', {}).get('zones', [])
        if not zones:
            return None
        return zones[0]
    except Exception as e:
        print(f"Cloudflare fetch failed: {e}")
        return None


def parse_cf_today(cf_data):
    """Extract today's summary from Cloudflare data."""
    if not cf_data:
        return {}
    today_list = cf_data.get('today', [])
    if not today_list:
        return {}
    t = today_list[0]
    s = t.get('sum', {})
    u = t.get('uniq', {})
    return {
        'uniques': u.get('uniques', 0),
        'page_views': s.get('pageViews', 0),
        'requests': s.get('requests', 0),
        'threats': s.get('threats', 0),
        'bytes': s.get('bytes', 0),
        'countries': sorted(s.get('countryMap', []), key=lambda x: x.get('requests', 0), reverse=True)[:15],
        'status_codes': sorted(s.get('responseStatusMap', []), key=lambda x: x.get('requests', 0), reverse=True),
    }


def parse_cf_daily(cf_data):
    """Extract 7-day daily breakdown."""
    if not cf_data:
        return []
    return [
        {
            'date': d['dimensions']['date'],
            'uniques': d.get('uniq', {}).get('uniques', 0),
            'page_views': d.get('sum', {}).get('pageViews', 0),
            'requests': d.get('sum', {}).get('requests', 0),
            'threats': d.get('sum', {}).get('threats', 0),
        }
        for d in cf_data.get('daily', [])
    ]


def parse_cf_hourly(cf_data):
    """Extract 24h hourly breakdown."""
    if not cf_data:
        return []
    return [
        {
            'hour': d['dimensions']['datetime'][:13],
            'uniques': d.get('uniq', {}).get('uniques', 0),
            'page_views': d.get('sum', {}).get('pageViews', 0),
        }
        for d in cf_data.get('hourly', [])
    ]


# ── GoAccess data ────────────────────────────────────────────────────────────

def load_goaccess_data():
    """Load GoAccess JSON output. Returns dict or None."""
    if not os.path.exists(GOACCESS_JSON):
        return None
    try:
        with open(GOACCESS_JSON, encoding='utf-8', errors='replace') as f:
            return json.load(f)
    except Exception as e:
        print(f"GoAccess JSON load failed: {e}")
        return None


def parse_goaccess_top_paths(ga_data):
    """Extract top visited paths from GoAccess data."""
    if not ga_data:
        return []
    requests = ga_data.get('requests', {}).get('data', [])
    return [
        {'path': r.get('data', ''), 'hits': r.get('hits', {}).get('count', 0)}
        for r in requests[:15]
    ]


def parse_goaccess_top_referrers(ga_data):
    """Extract top referrers from GoAccess data."""
    if not ga_data:
        return []
    refs = ga_data.get('referrers', {}).get('data', [])
    result = []
    for r in refs[:10]:
        name = r.get('data', '')
        hits = r.get('hits', {}).get('count', 0)
        # GoAccess nests sub-items under 'items'
        if name and hits:
            result.append({'referrer': name, 'hits': hits})
        for sub in r.get('items', [])[:3]:
            sub_name = sub.get('data', '')
            sub_hits = sub.get('hits', {}).get('count', 0)
            if sub_name and sub_hits:
                result.append({'referrer': f'  {sub_name}', 'hits': sub_hits})
    return result[:15]


def parse_goaccess_visitors(ga_data):
    """Extract visitor summary from GoAccess data."""
    if not ga_data:
        return {}
    gen = ga_data.get('general', {})
    return {
        'total_requests': gen.get('total_requests', 0),
        'unique_visitors': gen.get('unique_visitors', 0),
        'generation_time': gen.get('date_time', ''),
    }


# ── Watcher stats ────────────────────────────────────────────────────────────

def load_watcher_stats():
    """Load watcher and drop stats from local files."""
    stats = {'active_watchers': 0, 'total_watchers': 0, 'drops_24h': 0, 'drops_total': 0}

    # Watchers
    try:
        with open(paths.WATCHERS_JSON) as f:
            watchers = json.load(f)
        stats['total_watchers'] = len(watchers)
        stats['active_watchers'] = sum(1 for w in watchers if w.get('active'))
        stats['unique_emails'] = len(set(w.get('email', '').lower() for w in watchers))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Drops
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        with open(paths.DROPS_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    stats['drops_total'] = stats.get('drops_total', 0) + 1
                    if (d.get('timestamp') or '') > cutoff_24h:
                        stats['drops_24h'] = stats.get('drops_24h', 0) + 1
                except Exception:
                    continue
    except FileNotFoundError:
        pass

    return stats


# ── API usage stats ─────────────────────────────────────────────────────────

def load_api_usage():
    """Load api_usage.jsonl and return summary dict."""
    result = {
        'total_calls': 0, 'total_in': 0, 'total_out': 0, 'total_cost': 0.0,
        'calls_24h': 0, 'in_24h': 0, 'out_24h': 0, 'cost_24h': 0.0,
        'by_caller': defaultdict(lambda: {'calls': 0, 'in': 0, 'out': 0}),
        'by_day': defaultdict(lambda: {'calls': 0, 'in': 0, 'out': 0}),
    }
    if not os.path.exists(paths.API_USAGE_JSONL):
        return result

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    try:
        with open(paths.API_USAGE_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    inp = e.get('input_tokens', 0)
                    out = e.get('output_tokens', 0)
                    cost = (inp / 1_000_000 * INPUT_COST_PER_M) + (out / 1_000_000 * OUTPUT_COST_PER_M)

                    result['total_calls'] += 1
                    result['total_in'] += inp
                    result['total_out'] += out
                    result['total_cost'] += cost

                    ts = e.get('ts', '')
                    if ts >= cutoff_24h:
                        result['calls_24h'] += 1
                        result['in_24h'] += inp
                        result['out_24h'] += out
                        result['cost_24h'] += cost

                    caller = e.get('caller', 'unknown')
                    result['by_caller'][caller]['calls'] += 1
                    result['by_caller'][caller]['in'] += inp
                    result['by_caller'][caller]['out'] += out

                    day = ts[:10]
                    result['by_day'][day]['calls'] += 1
                    result['by_day'][day]['in'] += inp
                    result['by_day'][day]['out'] += out
                except Exception:
                    continue
    except FileNotFoundError:
        pass

    return result


# ── Formatting helpers ───────────────────────────────────────────────────────

def fmt_bytes(b):
    if b >= 1_073_741_824:
        return f'{b / 1_073_741_824:.1f} GB'
    if b >= 1_048_576:
        return f'{b / 1_048_576:.1f} MB'
    if b >= 1024:
        return f'{b / 1024:.1f} KB'
    return f'{b} B'


def fmt_num(n):
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n / 1_000:.1f}K'
    return str(n)


# ── HTML generation ──────────────────────────────────────────────────────────

def generate_traffic_page():
    print("Generating traffic dashboard...")

    cf_data = fetch_cloudflare_data()
    cf_today = parse_cf_today(cf_data)
    cf_daily = parse_cf_daily(cf_data)
    cf_hourly = parse_cf_hourly(cf_data)

    ga_data = load_goaccess_data()
    ga_paths = parse_goaccess_top_paths(ga_data)
    ga_refs = parse_goaccess_top_referrers(ga_data)
    ga_visitors = parse_goaccess_visitors(ga_data)

    watcher_stats = load_watcher_stats()
    api_usage = load_api_usage()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

    # ── Summary cards ────────────────────────────────────────────────────────
    uniques = cf_today.get('uniques', ga_visitors.get('unique_visitors', 0))
    page_views = cf_today.get('page_views', 0)
    requests = cf_today.get('requests', ga_visitors.get('total_requests', 0))
    threats = cf_today.get('threats', 0)
    bandwidth = cf_today.get('bytes', 0)

    cards_html = f"""
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">UNIQUE VISITORS</div>
        <div class="stat-value">{fmt_num(uniques)}</div>
        <div class="stat-sub">today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">PAGE VIEWS</div>
        <div class="stat-value">{fmt_num(page_views)}</div>
        <div class="stat-sub">today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">REQUESTS</div>
        <div class="stat-value">{fmt_num(requests)}</div>
        <div class="stat-sub">today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">THREATS BLOCKED</div>
        <div class="stat-value" style="color:{('#2ecc71' if threats == 0 else '#e74c3c')}">{threats}</div>
        <div class="stat-sub">today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">BANDWIDTH</div>
        <div class="stat-value">{fmt_bytes(bandwidth)}</div>
        <div class="stat-sub">today</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">ACTIVE WATCHERS</div>
        <div class="stat-value" style="color:var(--flame)">{watcher_stats.get('active_watchers', 0)}</div>
        <div class="stat-sub">{watcher_stats.get('unique_emails', 0)} emails</div>
      </div>
    </div>"""

    # ── 7-day bar chart ──────────────────────────────────────────────────────
    bars_html = ''
    if cf_daily:
        max_uniques = max((d['uniques'] for d in cf_daily), default=1) or 1
        bars = []
        for d in cf_daily:
            pct = int((d['uniques'] / max_uniques) * 100)
            day_label = d['date'][5:]  # MM-DD
            bars.append(f"""
              <div class="bar-col">
                <div class="bar-value">{d['uniques']}</div>
                <div class="bar" style="height:{max(pct, 2)}%"></div>
                <div class="bar-label">{day_label}</div>
              </div>""")
        bars_html = f"""
        <div class="section-head">7-DAY TREND</div>
        <div class="bar-chart">{''.join(bars)}</div>"""

    # ── 24h hourly chart ─────────────────────────────────────────────────────
    hourly_html = ''
    if cf_hourly:
        max_h = max((h['uniques'] for h in cf_hourly), default=1) or 1
        h_bars = []
        for h in cf_hourly:
            pct = int((h['uniques'] / max_h) * 100)
            hr = h['hour'][-2:]  # HH
            h_bars.append(f"""
              <div class="bar-col bar-col-sm">
                <div class="bar bar-sm" style="height:{max(pct, 2)}%"></div>
                <div class="bar-label">{hr}</div>
              </div>""")
        hourly_html = f"""
        <div class="section-head">LAST 24 HOURS</div>
        <div class="bar-chart bar-chart-hourly">{''.join(h_bars)}</div>"""

    # ── Top paths ────────────────────────────────────────────────────────────
    paths_html = '<div class="panel-empty">No path data available</div>'
    if ga_paths:
        total_hits = sum(p['hits'] for p in ga_paths) or 1
        rows = ''.join(
            f'<tr><td class="path-cell">{html_mod.escape(p["path"])}</td>'
            f'<td class="num-cell">{p["hits"]}</td>'
            f'<td class="num-cell">{int(p["hits"] / total_hits * 100)}%</td></tr>'
            for p in ga_paths
        )
        paths_html = f"""
        <table class="data-table">
          <thead><tr><th>PATH</th><th>HITS</th><th>%</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    # ── Top referrers ────────────────────────────────────────────────────────
    refs_html = '<div class="panel-empty">No referrer data available</div>'
    if ga_refs:
        rows = ''.join(
            f'<tr><td>{html_mod.escape(r["referrer"])}</td><td class="num-cell">{r["hits"]}</td></tr>'
            for r in ga_refs
        )
        refs_html = f"""
        <table class="data-table">
          <thead><tr><th>REFERRER</th><th>HITS</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    # ── Countries ────────────────────────────────────────────────────────────
    countries_html = '<div class="panel-empty">No country data available</div>'
    countries = cf_today.get('countries', [])
    if countries:
        rows = ''.join(
            f'<tr><td>{html_mod.escape(c.get("clientCountryName", "Unknown"))}</td>'
            f'<td class="num-cell">{c.get("requests", 0)}</td></tr>'
            for c in countries
        )
        countries_html = f"""
        <table class="data-table">
          <thead><tr><th>COUNTRY</th><th>REQUESTS</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    # ── Status codes ─────────────────────────────────────────────────────────
    status_html = '<div class="panel-empty">No status code data available</div>'
    status_codes = cf_today.get('status_codes', [])
    if status_codes:
        rows = ''.join(
            f'<tr><td><span class="status-dot" style="background:{status_color(c.get("edgeResponseStatus", 0))}"></span>'
            f'{c.get("edgeResponseStatus", "?")}</td>'
            f'<td class="num-cell">{c.get("requests", 0)}</td></tr>'
            for c in status_codes
        )
        status_html = f"""
        <table class="data-table">
          <thead><tr><th>STATUS</th><th>REQUESTS</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    # ── API usage section ───────────────────────────────────────────────────
    api_usage_html = ''
    if api_usage['total_calls'] > 0:
        # Caller breakdown table
        caller_rows = ''
        for caller, d in sorted(api_usage['by_caller'].items()):
            cost = (d['in'] / 1_000_000 * INPUT_COST_PER_M) + (d['out'] / 1_000_000 * OUTPUT_COST_PER_M)
            caller_rows += (
                f'<tr><td>{html_mod.escape(caller)}</td>'
                f'<td class="num-cell">{d["calls"]}</td>'
                f'<td class="num-cell">{d["in"]:,}</td>'
                f'<td class="num-cell">{d["out"]:,}</td>'
                f'<td class="num-cell">${cost:.4f}</td></tr>'
            )

        # Daily breakdown table (last 7 days)
        day_rows = ''
        for day in sorted(api_usage['by_day'].keys())[-7:]:
            d = api_usage['by_day'][day]
            cost = (d['in'] / 1_000_000 * INPUT_COST_PER_M) + (d['out'] / 1_000_000 * OUTPUT_COST_PER_M)
            day_rows += (
                f'<tr><td>{day}</td>'
                f'<td class="num-cell">{d["calls"]}</td>'
                f'<td class="num-cell">{d["in"]:,}</td>'
                f'<td class="num-cell">{d["out"]:,}</td>'
                f'<td class="num-cell">${cost:.4f}</td></tr>'
            )

        api_usage_html = f"""
    <div class="section-head">API TOKEN USAGE</div>
    <div class="stats-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 1.5rem;">
      <div class="stat-card">
        <div class="stat-label">CALLS (24H)</div>
        <div class="stat-value">{api_usage['calls_24h']}</div>
        <div class="stat-sub">{api_usage['total_calls']} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">INPUT TOKENS (24H)</div>
        <div class="stat-value">{fmt_num(api_usage['in_24h'])}</div>
        <div class="stat-sub">{fmt_num(api_usage['total_in'])} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">OUTPUT TOKENS (24H)</div>
        <div class="stat-value">{fmt_num(api_usage['out_24h'])}</div>
        <div class="stat-sub">{fmt_num(api_usage['total_out'])} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">EST. COST (24H)</div>
        <div class="stat-value" style="color:var(--flame)">${api_usage['cost_24h']:.4f}</div>
        <div class="stat-sub">${api_usage['total_cost']:.4f} total</div>
      </div>
    </div>

    <div class="panels">
      <div class="panel">
        <div class="panel-title">BY CALLER</div>
        <div class="panel-body">
          <table class="data-table">
            <thead><tr><th>CALLER</th><th>CALLS</th><th>IN</th><th>OUT</th><th>COST</th></tr></thead>
            <tbody>{caller_rows}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-title">DAILY (LAST 7 DAYS)</div>
        <div class="panel-body">
          <table class="data-table">
            <thead><tr><th>DAY</th><th>CALLS</th><th>IN</th><th>OUT</th><th>COST</th></tr></thead>
            <tbody>{day_rows}</tbody>
          </table>
        </div>
      </div>
    </div>"""

    # ── Data source indicator ────────────────────────────────────────────────
    sources = []
    if cf_data:
        sources.append('Cloudflare')
    if ga_data:
        sources.append(f'GoAccess ({ga_visitors.get("generation_time", "?")})')
    sources.append('Local')
    source_str = ' + '.join(sources)

    # ── Full page ────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="120">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>Traffic — Drop Watcher</title>
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

    /* Nav */
    .nav {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; font-size: 0.75rem; letter-spacing: 0.2em; flex-wrap: wrap; }}
    .nav a {{ color: var(--ash); text-decoration: none; }}
    .nav a:hover {{ color: var(--flame); }}
    .nav a.active {{ color: var(--flame); border-bottom: 1px solid var(--flame); }}

    /* Stats grid */
    .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--iron); border: 1px solid var(--iron); margin-bottom: 2rem; }}
    .stat-card {{ background: var(--black); padding: 1.2rem 0.5rem; text-align: center; }}
    .stat-label {{ font-size: 0.55rem; letter-spacing: 0.15em; color: var(--ash); margin-bottom: 0.3rem; }}
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
    .panel-empty {{ padding: 1.5rem; color: var(--ash); font-size: 0.75rem; text-align: center; }}

    /* Data tables */
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.7rem; }}
    .data-table th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--ash); font-size: 0.6rem; letter-spacing: 0.15em; border-bottom: 1px solid var(--iron); white-space: nowrap; }}
    .data-table td {{ padding: 0.4rem 0.75rem; border-bottom: 1px solid rgba(42,42,42,0.5); color: var(--silver); }}
    .data-table tr:last-child td {{ border-bottom: none; }}
    .data-table tr:hover td {{ background: var(--steel); }}
    .num-cell {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .path-cell {{ max-width: 55vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .status-dot {{ display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 6px; }}

    /* Desktop: side-by-side panels */
    @media (min-width: 700px) {{
      .stats-grid {{ grid-template-columns: repeat(6, 1fr); }}
      .panels {{ grid-template-columns: repeat(2, 1fr); }}
      .path-cell {{ max-width: 280px; }}
    }}

    /* Footer */
    .source-line {{ color: var(--ash); font-size: 0.6rem; letter-spacing: 0.15em; margin-top: 0.5rem; }}
    footer {{ margin-top: 2rem; color: var(--ash); font-size: 0.65rem; letter-spacing: 0.3em; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }}
    .hgr {{ font-family: 'Bebas Neue', sans-serif; color: var(--ember); font-size: 1.2rem; }}
  </style>
</head>
<body>
  <h1>DROP <span>WATCHER</span></h1>
  <p class="subtitle">TRAFFIC DASHBOARD — AUTO REFRESHES EVERY 2 MINUTES</p>
  <div class="flame-line"></div>

  <nav class="nav">
    <a href="/watcher_status.html">DASHBOARD</a>
    <a href="/alerts.html">ALERTS</a>
    <a href="/status.html">STATUS</a>
    <a href="/traffic.html" class="active">TRAFFIC</a>
    <a href="/stats/">STATS</a>
    <a href="/index.html">HOME</a>
  </nav>

  {cards_html}

  {bars_html}

  {hourly_html}

  <div class="panels">
    <div class="panel">
      <div class="panel-title">TOP PATHS</div>
      <div class="panel-body">{paths_html}</div>
    </div>
    <div class="panel">
      <div class="panel-title">TOP REFERRERS</div>
      <div class="panel-body">{refs_html}</div>
    </div>
  </div>

  <div class="panels">
    <div class="panel">
      <div class="panel-title">COUNTRIES</div>
      <div class="panel-body">{countries_html}</div>
    </div>
    <div class="panel">
      <div class="panel-title">STATUS CODES</div>
      <div class="panel-body">{status_html}</div>
    </div>
  </div>

  {api_usage_html}

  <p class="source-line">Sources: {source_str} — Updated: {now_str}</p>
  <p class="source-line"><a href="/stats/" style="color:var(--flame);text-decoration:none">Full GoAccess server stats →</a></p>

  <footer>
    <span>instockornot.club — simonhg321/drop-watcher</span>
    <span class="hgr" data-nosnippet>HGR</span>
  </footer>
</body>
</html>"""

    try:
        os.makedirs(os.path.dirname(TRAFFIC_HTML), exist_ok=True)
        with open(TRAFFIC_HTML, 'w') as f:
            f.write(html)
        print(f"✓ Traffic page written — {now_str}")
    except PermissionError:
        print(f"✗ Cannot write to {TRAFFIC_HTML} — check permissions")


def status_color(code):
    if code is None:
        return '#888'
    code = int(code) if code else 0
    if 200 <= code < 300:
        return '#2ecc71'
    if 300 <= code < 400:
        return '#3498db'
    if code == 403:
        return '#e74c3c'
    if code == 404:
        return '#e67e22'
    if code == 429:
        return '#f1c40f'
    if code >= 500:
        return '#e74c3c'
    return '#888'


if __name__ == '__main__':
    generate_traffic_page()
