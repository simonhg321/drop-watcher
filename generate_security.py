# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
generate_security.py
Drop Watcher — Apache Log Security Report
Parses access logs, flags scrapers, scanners, and rate abusers.
Outputs static HTML to /var/www/html/security.html
Cron: */10 * * * *
HGR
"""

import os
import re
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import paths

log = logging.getLogger('generate_security')

# ── Config ───────────────────────────────────────────────────────────────────
APACHE_LOG = os.environ.get('DW_APACHE_LOG', '/var/log/apache2/access.log')
SECURITY_HTML = paths.SECURITY_HTML
LOOKBACK_HOURS = 24
RATE_THRESHOLD = 100        # requests per IP in 5-min window = suspicious
SCANNER_THRESHOLD = 5       # 404s from one IP = scanner

# Known bad user agents (substrings, lowercase)
BAD_UA_PATTERNS = [
    'scrapy', 'python-requests', 'python-urllib', 'go-http-client',
    'curl/', 'wget/', 'nikto', 'sqlmap', 'nmap', 'masscan',
    'zgrab', 'censys', 'shodan', 'semrush', 'ahrefs', 'mj12bot',
    'dotbot', 'bytespider', 'petalbot', 'yandexbot',
    'dataforseo', 'blexbot', 'seekport',
]

# Scanner paths — things only bots hit
SCANNER_PATHS = [
    '/wp-admin', '/wp-login', '/wp-content', '/wordpress',
    '/.env', '/.git', '/.aws', '/.ssh',
    '/phpmyadmin', '/pma', '/myadmin', '/phpMyAdmin',
    '/admin', '/administrator', '/login',
    '/cgi-bin', '/shell', '/cmd', '/eval',
    '/xmlrpc.php', '/wp-cron.php',
    '/config.json', '/config.yaml', '/config.php',
    '/backup', '/db', '/dump', '/sql',
    '/actuator', '/api/v1', '/graphql',
    '/.well-known/security.txt',
]

# Apache Combined Log Format regex
LOG_PATTERN = re.compile(
    r'^(\S+)\s+'           # IP
    r'\S+\s+'              # ident
    r'\S+\s+'              # user
    r'\[([^\]]+)\]\s+'     # timestamp
    r'"(\S+)\s+'           # method
    r'(\S+)\s+'            # path
    r'\S+"\s+'             # protocol
    r'(\d{3})\s+'          # status
    r'(\S+)\s+'            # bytes
    r'"([^"]*)"\s+'        # referrer
    r'"([^"]*)"'           # user agent
)


def parse_log_line(line):
    m = LOG_PATTERN.match(line)
    if not m:
        return None
    ip, ts_str, method, path, status, size, referrer, ua = m.groups()
    try:
        ts = datetime.strptime(ts_str, '%d/%b/%Y:%H:%M:%S %z')
    except ValueError:
        return None
    return {
        'ip': ip,
        'ts': ts,
        'method': method,
        'path': path,
        'status': int(status),
        'size': int(size) if size != '-' else 0,
        'referrer': referrer,
        'ua': ua,
    }


def is_bad_ua(ua):
    ua_lower = ua.lower()
    if not ua or ua == '-':
        return True, 'empty'
    for pattern in BAD_UA_PATTERNS:
        if pattern in ua_lower:
            return True, pattern
    return False, None


def is_scanner_path(path):
    path_lower = path.lower()
    for sp in SCANNER_PATHS:
        if path_lower.startswith(sp.lower()):
            return True
    return False


def analyze_logs():
    if not os.path.exists(APACHE_LOG):
        log.warning(f"Apache log not found: {APACHE_LOG}")
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    # Accumulators
    ip_requests = defaultdict(int)
    ip_bytes = defaultdict(int)
    ip_ua = defaultdict(set)
    ip_paths = defaultdict(set)
    ip_404s = defaultdict(int)
    ip_scanner_hits = defaultdict(list)
    bad_ua_hits = defaultdict(list)     # ua_pattern -> list of IPs
    path_counts = defaultdict(int)
    status_counts = defaultdict(int)
    ip_timestamps = defaultdict(list)
    total_requests = 0
    total_bytes = 0
    scanner_attempts = []

    try:
        with open(APACHE_LOG, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                entry = parse_log_line(line.strip())
                if not entry:
                    continue
                if entry['ts'] < cutoff:
                    continue

                ip = entry['ip']
                total_requests += 1
                total_bytes += entry['size']

                ip_requests[ip] += 1
                ip_bytes[ip] += entry['size']
                ip_ua[ip].add(entry['ua'][:80])
                ip_paths[ip].add(entry['path'])
                ip_timestamps[ip].append(entry['ts'])
                path_counts[entry['path']] += 1
                status_counts[entry['status']] += 1

                if entry['status'] == 404:
                    ip_404s[ip] += 1

                bad, pattern = is_bad_ua(entry['ua'])
                if bad:
                    bad_ua_hits[pattern or 'empty'].append(ip)

                if is_scanner_path(entry['path']):
                    ip_scanner_hits[ip].append(entry['path'])
                    scanner_attempts.append(entry)

    except Exception as e:
        log.error(f"Error reading Apache log: {e}")
        return None

    # ── Rate abuse detection (100+ reqs in any 5-min window) ─────────────
    rate_abusers = {}
    for ip, timestamps in ip_timestamps.items():
        if len(timestamps) < RATE_THRESHOLD:
            continue
        timestamps.sort()
        window = timedelta(minutes=5)
        max_rate = 0
        for i, ts in enumerate(timestamps):
            j = i
            while j < len(timestamps) and timestamps[j] - ts <= window:
                j += 1
            rate = j - i
            if rate > max_rate:
                max_rate = rate
        if max_rate >= RATE_THRESHOLD:
            rate_abusers[ip] = max_rate

    # ── Build results ────────────────────────────────────────────────────
    top_ips = sorted(ip_requests.items(), key=lambda x: x[1], reverse=True)[:25]
    top_404_ips = sorted(ip_404s.items(), key=lambda x: x[1], reverse=True)[:15]
    scanners = {ip: paths for ip, paths in ip_scanner_hits.items() if len(paths) >= 2}
    top_paths = sorted(path_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    # Unique bad UAs
    bad_ua_summary = {}
    for pattern, ips in bad_ua_hits.items():
        bad_ua_summary[pattern] = len(set(ips))
    bad_ua_summary = dict(sorted(bad_ua_summary.items(), key=lambda x: x[1], reverse=True)[:15])

    return {
        'total_requests': total_requests,
        'total_bytes': total_bytes,
        'unique_ips': len(ip_requests),
        'top_ips': top_ips,
        'top_404_ips': top_404_ips,
        'scanners': scanners,
        'scanner_attempts': len(scanner_attempts),
        'rate_abusers': rate_abusers,
        'bad_ua_summary': bad_ua_summary,
        'status_counts': dict(sorted(status_counts.items())),
        'top_paths': top_paths,
        'ip_ua': ip_ua,
        'ip_requests': ip_requests,
        'ip_bytes': dict(ip_bytes),
        'ip_404s': ip_404s,
    }


def fmt_bytes(b):
    if b > 1_000_000_000:
        return f"{b / 1_000_000_000:.1f} GB"
    if b > 1_000_000:
        return f"{b / 1_000_000:.1f} MB"
    if b > 1_000:
        return f"{b / 1_000:.1f} KB"
    return f"{b} B"


def generate_html(data):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Threat count ─────────────────────────────────────────────────────
    threat_count = len(data['scanners']) + len(data['rate_abusers'])
    threat_color = 'var(--ember)' if threat_count > 0 else '#27ae60'

    # ── Stats grid ───────────────────────────────────────────────────────
    stats_html = f"""
    <div class="stats-grid">
      <div class="stat"><div class="num">{data['total_requests']:,}</div><div class="label">Requests (24h)</div></div>
      <div class="stat"><div class="num">{data['unique_ips']:,}</div><div class="label">Unique IPs</div></div>
      <div class="stat"><div class="num">{fmt_bytes(data['total_bytes'])}</div><div class="label">Bandwidth</div></div>
      <div class="stat"><div class="num" style="color:{threat_color}">{threat_count}</div><div class="label">Threats</div></div>
      <div class="stat"><div class="num">{data['scanner_attempts']:,}</div><div class="label">Scanner Hits</div></div>
      <div class="stat"><div class="num">{len(data['bad_ua_summary']):,}</div><div class="label">Bad UA Types</div></div>
    </div>"""

    # ── Rate abusers ─────────────────────────────────────────────────────
    rate_html = ''
    if data['rate_abusers']:
        rows = ''
        for ip, rate in sorted(data['rate_abusers'].items(), key=lambda x: x[1], reverse=True):
            ua_list = ', '.join(list(data['ip_ua'].get(ip, {'?'}))[:2])
            rows += f'<tr><td class="ip">{ip}</td><td class="num-cell">{rate}</td><td class="ua-cell">{ua_list[:60]}</td></tr>\n'
        rate_html = f"""
    <div class="panel threat">
      <h2>RATE ABUSERS <span class="badge">{len(data['rate_abusers'])}</span></h2>
      <p class="panel-sub">{RATE_THRESHOLD}+ requests in any 5-minute window</p>
      <table>{rows}</table>
    </div>"""

    # ── Scanners ─────────────────────────────────────────────────────────
    scanner_html = ''
    if data['scanners']:
        rows = ''
        for ip, paths in sorted(data['scanners'].items(), key=lambda x: len(x[1]), reverse=True)[:15]:
            path_sample = ', '.join(sorted(set(paths))[:4])
            rows += f'<tr><td class="ip">{ip}</td><td class="num-cell">{len(paths)}</td><td class="path-cell">{path_sample}</td></tr>\n'
        scanner_html = f"""
    <div class="panel threat">
      <h2>SCANNERS <span class="badge">{len(data['scanners'])}</span></h2>
      <p class="panel-sub">IPs probing known attack paths (wp-admin, .env, phpMyAdmin, etc.)</p>
      <table>{rows}</table>
    </div>"""

    # ── Bad user agents ──────────────────────────────────────────────────
    bad_ua_html = ''
    if data['bad_ua_summary']:
        rows = ''
        for pattern, count in data['bad_ua_summary'].items():
            rows += f'<tr><td class="ua-cell">{pattern}</td><td class="num-cell">{count} IPs</td></tr>\n'
        bad_ua_html = f"""
    <div class="panel">
      <h2>BAD USER AGENTS</h2>
      <p class="panel-sub">Known scrapers, bots, and empty UAs</p>
      <table>{rows}</table>
    </div>"""

    # ── Top IPs ──────────────────────────────────────────────────────────
    top_ip_rows = ''
    for ip, count in data['top_ips']:
        is_threat = ip in data['scanners'] or ip in data['rate_abusers']
        flag = ' <span class="threat-flag">!</span>' if is_threat else ''
        n404 = data['ip_404s'].get(ip, 0)
        n404_str = f'<span class="s404">{n404}</span>' if n404 > 0 else '0'
        top_ip_rows += f'<tr><td class="ip">{ip}{flag}</td><td class="num-cell">{count:,}</td><td class="num-cell">{n404_str}</td><td class="num-cell">{fmt_bytes(data["ip_bytes"].get(ip, 0) if "ip_bytes" in data else 0)}</td></tr>\n'

    top_ips_html = f"""
    <div class="panel">
      <h2>TOP IPs</h2>
      <table>
        <tr class="header"><td>IP</td><td>Reqs</td><td>404s</td><td>Bytes</td></tr>
        {top_ip_rows}
      </table>
    </div>"""

    # ── 404 Scanners ─────────────────────────────────────────────────────
    top_404_rows = ''
    for ip, count in data['top_404_ips'][:10]:
        if count < 3:
            continue
        is_threat = ip in data['scanners'] or ip in data['rate_abusers']
        flag = ' <span class="threat-flag">!</span>' if is_threat else ''
        top_404_rows += f'<tr><td class="ip">{ip}{flag}</td><td class="num-cell">{count}</td></tr>\n'

    top_404_html = ''
    if top_404_rows:
        top_404_html = f"""
    <div class="panel">
      <h2>TOP 404 SOURCES</h2>
      <p class="panel-sub">IPs generating the most 404s</p>
      <table>{top_404_rows}</table>
    </div>"""

    # ── Status codes ─────────────────────────────────────────────────────
    status_rows = ''
    for code, count in data['status_counts'].items():
        color = '#27ae60' if 200 <= code < 300 else 'var(--flame)' if 300 <= code < 400 else 'var(--ember)' if code >= 400 else 'var(--silver)'
        status_rows += f'<tr><td style="color:{color}">{code}</td><td class="num-cell">{count:,}</td></tr>\n'

    status_html = f"""
    <div class="panel">
      <h2>STATUS CODES</h2>
      <table>{status_rows}</table>
    </div>"""

    # ── Top paths ────────────────────────────────────────────────────────
    top_path_rows = ''
    for path, count in data['top_paths']:
        top_path_rows += f'<tr><td class="path-cell">{path[:60]}</td><td class="num-cell">{count:,}</td></tr>\n'

    top_paths_html = f"""
    <div class="panel">
      <h2>TOP PATHS</h2>
      <table>{top_path_rows}</table>
    </div>"""

    # ── Full page ────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>Drop Watcher — Security</title>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --black: #0a0a0a; --steel: #1c1c1c; --iron: #2a2a2a;
      --ember: #c0392b; --flame: #e67e22; --ash: #888;
      --silver: #d0d0d0; --white: #f0f0f0;
    }}
    body {{
      background: var(--black); color: var(--white);
      font-family: 'Share Tech Mono', monospace;
      min-height: 100vh;
    }}
    nav {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 1.5rem 2rem; border-bottom: 1px solid var(--iron);
    }}
    nav a.logo {{
      font-family: 'Bebas Neue', sans-serif; font-size: 1.4rem;
      letter-spacing: 3px; text-decoration: none; color: var(--white);
    }}
    nav a.logo span {{ color: var(--ember); }}
    nav .nav-links {{ display: flex; gap: 1.5rem; }}
    nav .nav-links a {{
      color: var(--ash); text-decoration: none; font-size: 0.75rem;
      letter-spacing: 1px; text-transform: uppercase;
    }}
    nav .nav-links a:hover {{ color: var(--white); }}

    .container {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}

    h1 {{
      font-family: 'Bebas Neue', sans-serif; font-size: 2.4rem;
      letter-spacing: 4px; margin-bottom: 0.3rem;
    }}
    h1 span {{ color: var(--ember); }}
    .updated {{ font-size: 0.7rem; color: var(--ash); margin-bottom: 2rem; }}

    .stats-grid {{
      display: grid; grid-template-columns: repeat(6, 1fr);
      gap: 0.8rem; margin-bottom: 2rem;
    }}
    .stat {{
      background: var(--steel); border: 1px solid var(--iron);
      padding: 1rem; text-align: center;
    }}
    .stat .num {{
      font-family: 'Bebas Neue', sans-serif; font-size: 1.8rem; color: var(--ember);
    }}
    .stat .label {{
      font-size: 0.6rem; letter-spacing: 1px; text-transform: uppercase;
      color: var(--ash); margin-top: 0.2rem;
    }}

    .panel {{
      background: var(--steel); border: 1px solid var(--iron);
      padding: 1.2rem; margin-bottom: 1rem;
    }}
    .panel.threat {{ border-left: 3px solid var(--ember); }}
    .panel h2 {{
      font-family: 'Bebas Neue', sans-serif; font-size: 1.3rem;
      letter-spacing: 2px; margin-bottom: 0.5rem; color: var(--white);
    }}
    .panel-sub {{
      font-size: 0.7rem; color: var(--ash); margin-bottom: 0.8rem;
    }}
    .badge {{
      background: var(--ember); color: var(--white); font-size: 0.7rem;
      padding: 0.15rem 0.5rem; vertical-align: middle; letter-spacing: 0;
      font-family: 'Share Tech Mono', monospace;
    }}

    table {{ width: 100%; border-collapse: collapse; }}
    tr {{ border-bottom: 1px solid var(--iron); }}
    tr.header {{ color: var(--ash); font-size: 0.65rem; letter-spacing: 1px; text-transform: uppercase; }}
    td {{ padding: 0.4rem 0.5rem; font-size: 0.8rem; }}
    .ip {{ color: var(--silver); font-family: 'Share Tech Mono', monospace; }}
    .num-cell {{ text-align: right; color: var(--white); }}
    .ua-cell {{ color: var(--ash); font-size: 0.7rem; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .path-cell {{ color: var(--flame); font-size: 0.75rem; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .s404 {{ color: var(--ember); }}
    .threat-flag {{ color: var(--ember); font-weight: bold; }}

    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}

    footer {{
      text-align: center; padding: 2rem 0; border-top: 1px solid var(--iron); margin-top: 2rem;
    }}
    footer .hgr {{
      font-family: 'Bebas Neue', sans-serif; font-size: 1.5rem;
      color: var(--ember); letter-spacing: 3px;
    }}
    footer .sub {{ font-size: 0.65rem; color: var(--ash); margin-top: 0.3rem; }}

    @media (max-width: 700px) {{
      .stats-grid {{ grid-template-columns: repeat(3, 1fr); }}
      .two-col {{ grid-template-columns: 1fr; }}
      .container {{ padding: 1.5rem 1rem 3rem; }}
      h1 {{ font-size: 1.8rem; }}
    }}
  </style>
</head>
<body>

<nav>
  <a href="/" class="logo">DROP <span>WATCHER</span></a>
  <div class="nav-links">
    <a href="/stats/dashboard.html">DASHBOARD</a>
    <a href="/stats/simon.html">DEEP DIVE</a>
    <a href="/stats/traffic.html">TRAFFIC</a>
    <a href="/stats/security.html">SECURITY</a>
    <a href="/stats/status.html">STATUS</a>
    <a href="/alerts.html">ALERTS</a>
    <a href="/">HOME</a>
  </div>
</nav>

<div class="container">
  <h1>SECURITY <span>REPORT</span></h1>
  <div class="updated">Last {LOOKBACK_HOURS}h &mdash; generated {now}</div>

  {stats_html}

  {rate_html}

  {scanner_html}

  {bad_ua_html}

  <div class="two-col">
    {top_ips_html}
    <div>
      {status_html}
      {top_404_html}
    </div>
  </div>

  {top_paths_html}

</div>

<footer>
  <div class="hgr">HGR</div>
  <div class="sub">instockornot.club</div>
</footer>

</body>
</html>"""

    return html


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')

    log.info("Analyzing Apache logs...")
    data = analyze_logs()

    if not data:
        log.warning("No data to report")
        return

    html = generate_html(data)

    with open(SECURITY_HTML, 'w') as f:
        f.write(html)

    log.info(f"Security report written to {SECURITY_HTML}")
    log.info(f"  {data['total_requests']:,} requests from {data['unique_ips']:,} IPs")
    log.info(f"  {len(data['scanners'])} scanners, {len(data['rate_abusers'])} rate abusers")


if __name__ == '__main__':
    main()
