#!/usr/bin/env python3
"""
preflight.py
Drop Watcher — Preflight Diagnostic
Runs health checks before agents start. Non-blocking — warns and logs but never stops the show.
HGR
"""

import html as html_mod
import os
import re
import sys
import json
import time
import shutil
import importlib
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import yaml
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from bs4 import BeautifulSoup

class PermissiveSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
LOG_DIR    = os.path.join(BASE_DIR, 'logs')
WWW_DIR    = '/var/www/html'
STATUS_HTML = os.path.join(WWW_DIR, 'status.html')

SOURCES_FILE   = os.path.join(CONFIG_DIR, 'sources.yaml')
COOL_LIST_FILE = os.path.join(CONFIG_DIR, 'cool_list.yaml')
MAKERS_FILE    = os.path.join(CONFIG_DIR, 'makers.yaml')
SETTINGS_FILE  = os.path.join(CONFIG_DIR, 'settings.yaml')

REQUIRED_PACKAGES = ['requests', 'yaml', 'bs4', 'feedparser', 'schedule']

# ── Terminal Colors ───────────────────────────────────────────────────────────
class C:
    RESET  = '\033[0m'
    BOLD   = '\033[1m'
    RED    = '\033[91m'
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    BLUE   = '\033[94m'
    CYAN   = '\033[96m'
    WHITE  = '\033[97m'
    DIM    = '\033[2m'

def ok(msg):    print(f"  {C.GREEN}✓{C.RESET}  {msg}")
def warn(msg):  print(f"  {C.YELLOW}⚠{C.RESET}  {msg}")
def err(msg):   print(f"  {C.RED}✗{C.RESET}  {msg}")
def info(msg):  print(f"  {C.CYAN}→{C.RESET}  {msg}")
def head(msg):  print(f"\n{C.BOLD}{C.WHITE}{msg}{C.RESET}")
def rule():     print(f"  {C.DIM}{'─' * 60}{C.RESET}")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; personal use)'
}

# ── YAML loader ───────────────────────────────────────────────────────────────
def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

# ── Results collector ─────────────────────────────────────────────────────────
results = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'system': {},
    'config': {},
    'sites': [],
    'feeds': [],
    'summary': {'pass': 0, 'warn': 0, 'fail': 0}
}

def tally(status):
    if status == 'pass':   results['summary']['pass'] += 1
    elif status == 'warn': results['summary']['warn'] += 1
    elif status == 'fail': results['summary']['fail'] += 1

# ─────────────────────────────────────────────────────────────────────────────
# 1. SYSTEM HEALTH
# ─────────────────────────────────────────────────────────────────────────────
def check_system():
    head("[ 1/6 ] SYSTEM HEALTH")
    rule()
    sys_results = {}

    # Python version
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v.major == 3 and v.minor >= 9:
        ok(f"Python {ver}")
        sys_results['python'] = {'status': 'pass', 'version': ver}
        tally('pass')
    else:
        warn(f"Python {ver} — recommend 3.9+")
        sys_results['python'] = {'status': 'warn', 'version': ver}
        tally('warn')

    # Required packages
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            ok(f"Package: {pkg}")
            tally('pass')
        except ImportError:
            err(f"Package missing: {pkg}")
            missing.append(pkg)
            tally('fail')
    sys_results['packages'] = {'missing': missing}

    # Disk space
    total, used, free = shutil.disk_usage(LOG_DIR if os.path.exists(LOG_DIR) else BASE_DIR)
    free_gb = free / (1024 ** 3)
    used_pct = (used / total) * 100
    if free_gb > 1:
        ok(f"Disk space: {free_gb:.1f}GB free ({used_pct:.0f}% used)")
        sys_results['disk'] = {'status': 'pass', 'free_gb': round(free_gb, 1), 'used_pct': round(used_pct)}
        tally('pass')
    elif free_gb > 0.2:
        warn(f"Disk space low: {free_gb:.1f}GB free ({used_pct:.0f}% used)")
        sys_results['disk'] = {'status': 'warn', 'free_gb': round(free_gb, 1), 'used_pct': round(used_pct)}
        tally('warn')
    else:
        err(f"Disk space critical: {free_gb:.1f}GB free!")
        sys_results['disk'] = {'status': 'fail', 'free_gb': round(free_gb, 1), 'used_pct': round(used_pct)}
        tally('fail')

    # Log directory
    os.makedirs(LOG_DIR, exist_ok=True)
    ok(f"Log directory: {LOG_DIR}")
    sys_results['log_dir'] = LOG_DIR

    # Check log sizes and rotation
    log_files = [f for f in os.listdir(LOG_DIR) if f.endswith(('.log', '.jsonl'))] if os.path.exists(LOG_DIR) else []
    for lf in log_files:
        lpath = os.path.join(LOG_DIR, lf)
        size_mb = os.path.getsize(lpath) / (1024 * 1024)
        if size_mb > 40:
            warn(f"Log {lf} is {size_mb:.1f}MB — consider rotation")
            tally('warn')
        else:
            ok(f"Log {lf}: {size_mb:.1f}MB")
            tally('pass')

    results['system'] = sys_results


# ─────────────────────────────────────────────────────────────────────────────
# 2. CONFIG VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
def check_configs():
    head("[ 2/6 ] CONFIG VALIDATION")
    rule()
    cfg_results = {}

    config_files = {
        'sources':   SOURCES_FILE,
        'cool_list': COOL_LIST_FILE,
        'makers':    MAKERS_FILE,
        'settings':  SETTINGS_FILE,
    }

    loaded = {}
    for name, path in config_files.items():
        if not os.path.exists(path):
            err(f"{name}.yaml — NOT FOUND at {path}")
            cfg_results[name] = {'status': 'fail', 'error': 'not found'}
            tally('fail')
            continue
        try:
            data = load_yaml(path)
            if data:
                ok(f"{name}.yaml — valid YAML ✓")
                cfg_results[name] = {'status': 'pass'}
                loaded[name] = data
                tally('pass')
            else:
                warn(f"{name}.yaml — file is empty")
                cfg_results[name] = {'status': 'warn', 'error': 'empty'}
                tally('warn')
        except yaml.YAMLError as e:
            err(f"{name}.yaml — INVALID YAML: {e}")
            cfg_results[name] = {'status': 'fail', 'error': str(e)}
            tally('fail')

    # Count makers and keywords
    if 'makers' in loaded:
        n_makers = len(loaded['makers'].get('makers', []))
        n_collabs = len(loaded['makers'].get('collaborations', []))
        info(f"{n_makers} makers configured, {n_collabs} collaborations")

    if 'cool_list' in loaded:
        kw_count = sum(len(v) for v in loaded['cool_list'].get('keywords', {}).values())
        info(f"{kw_count} keywords across all buckets")

    if 'sources' in loaded:
        n_sites = len([s for s in loaded['sources'].get('websites', []) if s.get('enabled', True)])
        n_feeds = len([f for f in loaded['sources'].get('feeds', []) if f.get('enabled', True)])
        info(f"{n_sites} websites enabled, {n_feeds} feeds enabled")

    results['config'] = cfg_results
    return loaded


# ─────────────────────────────────────────────────────────────────────────────
# 3. NETWORK & REACHABILITY
# ─────────────────────────────────────────────────────────────────────────────
def check_site(site, makers_list, keywords):
    name     = site['name']
    url      = site['url']
    interval = site.get('poll_interval', 20)

    site_result = {
        'name': name,
        'url': url,
        'poll_interval_min': interval,
        'status_code': None,
        'response_time_ms': None,
        'reachable': False,
        'blocked': False,
        'js_rendered': False,
        'has_sitemap': False,
        'robots_txt': None,
        'makers_found': [],
        'makers_in_stock': {},
        'makers_out_of_stock': {},
        'drop_announcements': [],
        'errors': []
    }

    info(f"Checking: {C.BOLD}{name}{C.RESET} ({url})")

    # ── Robots.txt ────────────────────────────────────────────────────────────
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        r = requests.get(robots_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            robots_text = r.text[:500]
            site_result['robots_txt'] = robots_text
            if 'disallow: /' in robots_text.lower():
                warn(f"  robots.txt disallows root — proceed with caution")
            else:
                ok(f"  robots.txt: fetched")
        else:
            site_result['robots_txt'] = 'not found'
            ok(f"  robots.txt: not found (that's fine)")
    except Exception as e:
        site_result['robots_txt'] = f'error: {e}'

    # ── Sitemap check ─────────────────────────────────────────────────────────
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    try:
        r = requests.get(sitemap_url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            site_result['has_sitemap'] = True
            ok(f"  sitemap.xml: found — could use for cleaner scraping")
        else:
            ok(f"  sitemap.xml: not found")
    except:
        pass

    # ── Main page fetch ───────────────────────────────────────────────────────
    start = time.time()
    try:
        ssl_permissive = site.get('ssl_permissive', False)
        session = requests.Session()
        if ssl_permissive:
            session.mount('https://', PermissiveSSLAdapter())
        response = session.get(url, headers=HEADERS, timeout=15, verify=not ssl_permissive)
        elapsed_ms = int((time.time() - start) * 1000)
        site_result['status_code'] = response.status_code
        site_result['response_time_ms'] = elapsed_ms

        if response.status_code == 200:
            site_result['reachable'] = True
            if elapsed_ms > 3000:
                warn(f"  {response.status_code} — slow response: {elapsed_ms}ms ⚠ (possible drop traffic?)")
                tally('warn')
            else:
                ok(f"  {response.status_code} — {elapsed_ms}ms")
                tally('pass')

        elif response.status_code == 403:
            site_result['blocked'] = True
            err(f"  403 FORBIDDEN — we are being blocked")
            tally('fail')
            return site_result

        elif response.status_code == 429:
            warn(f"  429 TOO MANY REQUESTS — slow down polling interval")
            tally('warn')
            return site_result

        else:
            warn(f"  {response.status_code} — unexpected status")
            tally('warn')
            return site_result

        # ── Content analysis ──────────────────────────────────────────────────
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)

        if len(text.strip()) < 200:
            site_result['js_rendered'] = True
            warn(f"  Very little text content — likely JavaScript rendered (we can't scrape this well)")
            tally('warn')
        else:
            ok(f"  Content: {len(text)} chars of text — scrapeable ✓")
            tally('pass')

        text_lower = text.lower()

        # ── Drop announcement detection ───────────────────────────────────────
        drop_phrases = [
            'dropping in', 'available friday', 'available saturday', 'available sunday',
            'available monday', 'available tuesday', 'available wednesday', 'available thursday',
            'launching', 'release date', 'drops at', 'available at noon',
        ]
        found_announcements = [p for p in drop_phrases if p in text_lower]
        if found_announcements:
            site_result['drop_announcements'] = found_announcements
            warn(f"  🔥 DROP ANNOUNCEMENT on {name}: {found_announcements}")
            tally('warn')

        # ── Maker detection ───────────────────────────────────────────────────
        for maker in makers_list:
            maker_name = maker['name'].lower()
            aliases = [a.lower() for a in maker.get('aliases', [])]
            all_terms = [maker_name] + aliases

            found = any(term in text_lower for term in all_terms)
            if found:
                site_result['makers_found'].append(maker['name'])

                in_stock_count = text_lower.count('in stock')
                out_stock_count = text_lower.count('out of stock') + text_lower.count('sold out')

                site_result['makers_in_stock'][maker['name']] = in_stock_count
                site_result['makers_out_of_stock'][maker['name']] = out_stock_count

                if out_stock_count > 0 and in_stock_count == 0:
                    warn(f"  {maker['name']}: FOUND but OUT OF STOCK ({out_stock_count} sold out items) — drop may have hit!")
                    tally('warn')
                elif in_stock_count > 0:
                    ok(f"  {maker['name']}: FOUND — ~{in_stock_count} in stock items")
                    tally('pass')
                else:
                    ok(f"  {maker['name']}: found on site")
                    tally('pass')
            else:
                info(f"  {maker['name']}: not found on this site")

    except requests.exceptions.Timeout:
        elapsed_ms = int((time.time() - start) * 1000)
        site_result['response_time_ms'] = elapsed_ms
        err(f"  TIMEOUT after {elapsed_ms}ms")
        site_result['errors'].append('timeout')
        tally('fail')

    except requests.exceptions.ConnectionError as e:
        err(f"  CONNECTION ERROR: {e}")
        site_result['errors'].append(str(e))
        tally('fail')

    except Exception as e:
        err(f"  ERROR: {e}")
        site_result['errors'].append(str(e))
        tally('fail')

    return site_result


def check_network(loaded):
    head("[ 3/6 ] NETWORK & REACHABILITY")
    rule()

    sources = loaded.get('sources', {})
    makers_list = loaded.get('makers', {}).get('makers', [])
    keywords = []
    for bucket in loaded.get('cool_list', {}).get('keywords', {}).values():
        keywords.extend([k.lower() for k in bucket])

    websites = [s for s in sources.get('websites', []) if s.get('enabled', True)]

    for site in websites:
        result = check_site(site, makers_list, keywords)
        results['sites'].append(result)
        time.sleep(2)


# ─────────────────────────────────────────────────────────────────────────────
# 4. FEED HEALTH
# ─────────────────────────────────────────────────────────────────────────────
def check_feeds(loaded):
    head("[ 4/6 ] FEED HEALTH")
    rule()

    import feedparser
    sources = loaded.get('sources', {})
    feeds = [f for f in sources.get('feeds', []) if f.get('enabled', True)]

    if not feeds:
        info("No feeds enabled yet — skipping feed health check")
        info("Add RSS bridge URLs to config/sources.yaml to enable feed watching")
        return

    for feed in feeds:
        name = feed['name']
        url  = feed['url']
        info(f"Checking feed: {name}")

        try:
            parsed = feedparser.parse(url)
            if parsed.bozo:
                err(f"  Invalid or malformed feed XML")
                results['feeds'].append({'name': name, 'status': 'fail', 'error': 'malformed'})
                tally('fail')
            else:
                entries = len(parsed.entries)
                last_pub = parsed.entries[0].get('published', 'unknown') if entries > 0 else 'no entries'
                ok(f"  Valid feed — {entries} entries, last published: {last_pub}")
                results['feeds'].append({'name': name, 'status': 'pass', 'entries': entries, 'last_published': last_pub})
                tally('pass')
        except Exception as e:
            err(f"  Feed error: {e}")
            results['feeds'].append({'name': name, 'status': 'fail', 'error': str(e)})
            tally('fail')


# ─────────────────────────────────────────────────────────────────────────────
# 5. SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
def print_summary():
    head("[ 5/6 ] SUMMARY")
    rule()
    s = results['summary']
    total = s['pass'] + s['warn'] + s['fail']
    print(f"  {C.GREEN}PASS{C.RESET}  {s['pass']}/{total}")
    print(f"  {C.YELLOW}WARN{C.RESET}  {s['warn']}/{total}")
    print(f"  {C.RED}FAIL{C.RESET}  {s['fail']}/{total}")

    if s['fail'] > 0:
        warn("Some checks failed — agents will still start but review errors above")
    elif s['warn'] > 0:
        ok("All critical checks passed — some warnings to review")
    else:
        ok("All checks passed — system is healthy")

    drops_found = []
    for site in results['sites']:
        if site.get('drop_announcements'):
            drops_found.append(site['name'])
    if drops_found:
        print(f"\n  {C.RED}{C.BOLD}🔥 DROP ANNOUNCEMENTS DETECTED ON: {', '.join(drops_found)}{C.RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. HTML STATUS PAGE
# ─────────────────────────────────────────────────────────────────────────────
def status_color(status_code):
    if status_code is None: return '#888'
    if status_code == 200: return '#2ecc71'
    if status_code == 403: return '#e74c3c'
    if status_code == 429: return '#e67e22'
    return '#f39c12'

def render_html_block():
    s  = results['summary']
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

    site_rows = ''
    for site in results['sites']:
        code     = site.get('status_code', '—')
        rt       = f"{site.get('response_time_ms', '—')}ms" if site.get('response_time_ms') else '—'
        color    = status_color(site.get('status_code'))
        blocked  = '🚫 BLOCKED' if site.get('blocked') else ''
        js_flag  = '⚠ JS rendered' if site.get('js_rendered') else ''
        sitemap  = '✓ sitemap' if site.get('has_sitemap') else ''
        makers   = ', '.join(html_mod.escape(m) for m in site.get('makers_found', [])) or '—'
        announce = ' | '.join(html_mod.escape(a) for a in site.get('drop_announcements', []))
        drop_row = f'<tr class="drop-alert"><td colspan="6">🔥 DROP ANNOUNCEMENT: {announce}</td></tr>' if announce else ''

        site_rows += f"""
        <tr>
            <td><a href="{html_mod.escape(site['url'])}" target="_blank">{html_mod.escape(site['name'])}</a></td>
            <td style="color:{color}">{code} {blocked}</td>
            <td>{rt}</td>
            <td>{js_flag} {sitemap}</td>
            <td>{makers}</td>
            <td>{site.get('poll_interval_min', '—')}m</td>
        </tr>
        {drop_row}
        """

    overall = 'HEALTHY' if s['fail'] == 0 else 'ISSUES DETECTED'
    overall_color = '#2ecc71' if s['fail'] == 0 else '#e74c3c'

    return f"""
    <div class="run-block">
        <div class="run-header">
            <span class="run-ts">{now_str}</span>
            <span class="run-status" style="color:{overall_color}">{overall}</span>
            <span class="run-counts">
                <span class="pass">✓ {s['pass']}</span>
                <span class="warn">⚠ {s['warn']}</span>
                <span class="fail">✗ {s['fail']}</span>
            </span>
        </div>
        <table class="site-table">
            <thead>
                <tr>
                    <th>Site</th>
                    <th>Status</th>
                    <th>Response</th>
                    <th>Scrape</th>
                    <th>Makers Found</th>
                    <th>Poll</th>
                </tr>
            </thead>
            <tbody>
                {site_rows}
            </tbody>
        </table>
    </div>
    """

def write_html_status():
    head("[ 6/6 ] GENERATING STATUS PAGE")
    rule()

    new_block = render_html_block()

    # Read existing run blocks and keep last 9 (new + 9 = 10 total)
    existing_blocks = ''
    if os.path.exists(STATUS_HTML):
        with open(STATUS_HTML, 'r') as f:
            content = f.read()
        marker_start = '<!-- RUNS_START -->'
        marker_end   = '<!-- RUNS_END -->'
        if marker_start in content and marker_end in content:
            start = content.index(marker_start) + len(marker_start)
            end   = content.index(marker_end)
            raw_blocks = content[start:end]
            # Extract individual run blocks, keep last 9
            blocks = re.findall(r'<div class="run-block">.*?</div>\s*</div>', raw_blocks, re.DOTALL)
            existing_blocks = '\n'.join(blocks[:9])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="60">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>Drop Watcher — Status</title>
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
    .run-block {{ border: 1px solid var(--iron); margin-bottom: 1.5rem; overflow-x: auto; }}
    .run-header {{ display: flex; gap: 1rem; align-items: center; padding: 0.75rem 1rem; background: var(--steel); border-bottom: 1px solid var(--iron); flex-wrap: wrap; }}
    .run-ts {{ color: var(--ash); font-size: 0.65rem; }}
    .run-status {{ font-family: 'Bebas Neue', sans-serif; font-size: 1.2rem; letter-spacing: 0.1em; }}
    .run-counts {{ display: flex; gap: 1rem; font-size: 0.75rem; margin-left: auto; }}
    .pass {{ color: #2ecc71; }} .warn {{ color: #e67e22; }} .fail {{ color: #e74c3c; }}
    .site-table {{ width: 100%; border-collapse: collapse; font-size: 0.7rem; min-width: 500px; }}
    .site-table th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--ember); font-size: 0.6rem; letter-spacing: 0.2em; border-bottom: 1px solid var(--iron); white-space: nowrap; }}
    .site-table td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--iron); color: var(--silver); }}
    .site-table tr:last-child td {{ border-bottom: none; }}
    .site-table tr:hover td {{ background: var(--steel); }}
    .site-table a {{ color: var(--silver); text-decoration: none; }}
    .site-table a:hover {{ color: var(--flame); }}
    .drop-alert td {{ background: rgba(192,57,43,0.15); color: var(--flame); font-weight: bold; }}
    footer {{ margin-top: 2rem; color: var(--ash); font-size: 0.65rem; letter-spacing: 0.3em; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }}
    .hgr {{ font-family: 'Bebas Neue', sans-serif; color: var(--ember); font-size: 1.2rem; }}
  </style>
</head>
<body>
  <h1>DROP <span>WATCHER</span></h1>
  <p class="subtitle">PREFLIGHT STATUS — AUTO REFRESHES EVERY 60 SECONDS — instockornot.club</p>
  <div class="flame-line"></div>

  <nav class="nav">
    <a href="/alerts.html">ALERTS</a>
    <a href="/status.html" class="active">STATUS</a>
    <a href="/index.html">HOME</a>
  </nav>

  <!-- RUNS_START -->
  {new_block}
  {existing_blocks}
  <!-- RUNS_END -->

  <footer>
    <span>instockornot.club — simonhg321/drop-watcher</span>
    <span class="hgr">HGR</span>
  </footer>
</body>
</html>"""

    try:
        with open(STATUS_HTML, 'w') as f:
            f.write(html)
        ok(f"Status page written to {STATUS_HTML}")
        ok(f"View at https://instockornot.club/status.html")
        tally('pass')
    except PermissionError:
        err(f"Cannot write to {STATUS_HTML} — run with sudo or fix permissions")
        info(f"Try: sudo chown shg:shg {STATUS_HTML} or sudo chmod 777 {WWW_DIR}")
        tally('warn')


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def run():
    print(f"\n{C.BOLD}{C.WHITE}{'═' * 64}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  DROP WATCHER — PREFLIGHT DIAGNOSTIC{C.RESET}")
    print(f"{C.DIM}  {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}{'═' * 64}{C.RESET}")

    check_system()
    loaded = check_configs()

    if not loaded:
        err("Cannot load configs — aborting network checks")
        return

    check_network(loaded)
    check_feeds(loaded)
    print_summary()
    write_html_status()

    # Write results to JSON log
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, 'preflight.jsonl')
    with open(log_path, 'a') as f:
        f.write(json.dumps(results) + '\n')

    print(f"\n{C.BOLD}{C.WHITE}{'═' * 64}{C.RESET}\n")


if __name__ == '__main__':
    run()
