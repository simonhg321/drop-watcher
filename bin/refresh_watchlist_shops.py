#!/usr/bin/env python3
"""
refresh_watchlist_shops.py — inject enabled shops from sources.yaml into watchlist.html.
Run manually when sources.yaml changes.
HGR
"""
import os, re, json
from urllib.parse import urlparse
import yaml

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES    = os.path.join(BASE_DIR, 'config', 'sources.yaml')
WATCHLIST  = os.path.join(BASE_DIR, 'html', 'watchlist.html')
DEPLOY     = '/var/www/html/watchlist.html'

def domain(url):
    h = urlparse(url).hostname or ''
    return h.lstrip('www.')

def main():
    with open(SOURCES) as f:
        data = yaml.safe_load(f)

    shops = []
    for s in data.get('websites', []):
        if not s.get('enabled', True):
            continue
        shops.append({
            'name':   s['name'],
            'url':    s['url'],
            'domain': domain(s['url']),
        })
    shops.sort(key=lambda s: s['name'].lower())

    with open(WATCHLIST) as f:
        html = f.read()

    block = f'<script id="dw-shops-data">\nconst DW_SHOPS = {json.dumps(shops, indent=2)};\n</script>'

    if '<script id="dw-shops-data">' in html:
        html = re.sub(
            r'<script id="dw-shops-data">.*?</script>',
            block,
            html,
            flags=re.DOTALL,
        )
    else:
        html = html.replace('</body>', block + '\n</body>')

    with open(WATCHLIST, 'w') as f:
        f.write(html)
    with open(DEPLOY, 'w') as f:
        f.write(html)

    print(f'Injected {len(shops)} shops → {DEPLOY}')

if __name__ == '__main__':
    main()
