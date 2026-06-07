# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
generate_cool_makers.py — build html/our-cool-makers.html, a downloadable, on-brand
list of every maker Drop Watcher follows (grouped by tier, straight from makers.yaml)
that visitors can save and use as personal bookmarks.

Links go to each maker's official site where we have a verified one (harvested from the
maker-direct entries in sources.yaml); everything else opens a quick search, so every
entry is a working bookmark and nothing is a guessed URL.

Run:  python3 generate_cool_makers.py   (writes html/our-cool-makers.html)
Re-run whenever makers.yaml changes to keep the list current.
HGR
"""

import os
import re
import html as html_mod
from urllib.parse import quote

import yaml

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MAKERS_YAML = os.path.join(BASE_DIR, 'config', 'makers.yaml')
OUT_FILE    = os.path.join(BASE_DIR, 'html', 'our-cool-makers.html')

# Verified official sites (from the maker-direct entries in sources.yaml). Anything not
# here falls back to a search link — we never guess an official URL.
OFFICIAL = {
    'Hinderer Knives':            'https://rickhindererknives.com',
    'Chris Reeve Knives':         'https://www.chrisreeve.com',
    'Steel Flame':                'https://www.steelflame.com',
    'Strider Knives':             'https://www.striderknives.com',
    'Mick Strider Custom Knives': 'https://mickstridercustomknives.com',
    'McNees Knives':              'https://mcneesknives.com',
    'Monkey Edge':                'https://www.monkeyedge.com',
    'Arno Bernard Knives':        'https://arnobernard.com',
    'Demko Knives':               'https://demkoknives.com',
    'Spyderco':                   'https://www.spyderco.com',
    'Curtiss Custom Knives':      'https://www.curtisscustomknives.com',
    'Prometheus Design Werx':     'https://prometheusdesignwerx.com',
    'Tactile Knife Co':           'https://www.tactileknife.com',
    'Oz Machine Company':         'https://ozmachinecompany.com',
    # Blade Show 2026 additions — verified maker-direct URLs from sources.yaml
    'Holt Bladeworks':            'https://holtbladeworks.com',
    'Grimsmo Knives':             'https://grimsmoknives.com',
    'Koenig Knives':              'https://koenigknives.com',
    'Zero Tolerance':             'https://www.zt.kaiusa.com/all-products.html',
    'Iron Ethos':                 'https://ironethos.com',
    'Chaves Knives':              'https://chavesknives.com',
}

TIER_LABELS = {
    '1': 'Tier 1 — Always Watching',
    '2': 'Tier 2 — On the Radar',
    '3': 'Tier 3 — Custom & Boutique',
}


def parse_tiers():
    """Walk makers.yaml in order, grouping maker names under their `# ── Tier N` headers."""
    tiers = []          # [(label, [names])]
    current = None
    for line in open(MAKERS_YAML):
        if line.lstrip().startswith('#'):
            m = re.search(r'Tier\s*([123])', line)
            if m:
                current = (TIER_LABELS[m.group(1)], [])
                tiers.append(current)
                continue
            # Any other box-drawing header ("# ── Label ──") starts its own section
            # (e.g. "Blade Show 2026 — Hot Makers"). Label = text between the rules.
            h = re.search(r'#\s*─+\s*(\S.*?)\s*─+\s*$', line)
            if h:
                current = (h.group(1), [])
                tiers.append(current)
                continue
        if line.startswith('collaborations:'):
            current = None
            continue
        nm = re.match(r'\s*-\s*name:\s*(.+?)\s*$', line)
        if nm and current is not None:
            current[1].append(nm.group(1))
    return tiers


def parse_collabs():
    data = yaml.safe_load(open(MAKERS_YAML)) or {}
    return [' × '.join(c.get('makers', [])) for c in data.get('collaborations', [])]


def link_for(name):
    url = OFFICIAL.get(name)
    return (url, True) if url else (f"https://duckduckgo.com/?q={quote(name + ' knives')}", False)


def render():
    tiers   = parse_tiers()
    collabs = parse_collabs()
    total   = sum(len(names) for _, names in tiers)

    sections = ''
    seen = set()   # dedupe: a maker renders once even if it appears under two headers
    for label, names in tiers:
        cards = ''
        for name in names:
            key = name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            url, official = link_for(name)
            tag = ('<span class="badge official">official site ↗</span>' if official
                   else '<span class="badge search">search ↗</span>')
            cards += (f'      <a class="maker" href="{html_mod.escape(url)}" '
                      f'target="_blank" rel="noopener">'
                      f'<span class="mname">{html_mod.escape(name)}</span>{tag}</a>\n')
        if not cards:        # skip empty sections (e.g. the Collaborations header,
            continue         # whose entries render below via parse_collabs)
        sections += (f'  <div class="section-head">{html_mod.escape(label.upper())}</div>\n'
                     f'    <div class="grid">\n{cards}    </div>\n')

    if collabs:
        chips = ''.join(f'      <div class="collab">{html_mod.escape(c)}</div>\n' for c in collabs)
        sections += ('  <div class="section-head">COLLABORATIONS — ALWAYS CRITICAL</div>\n'
                     f'    <div class="grid">\n{chips}    </div>\n')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>Our Cool Makers — Drop Watcher</title>
  <meta name="description" content="Every knife maker Drop Watcher follows, in one downloadable list you can save and use as personal bookmarks.">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="https://instockornot.club/our-cool-makers.html">
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --black: #0a0a0a; --steel: #1c1c1c; --iron: #2a2a2a;
      --ember: #c0392b; --flame: #e67e22; --ash: #888;
      --silver: #d0d0d0; --white: #f0f0f0;
    }}
    body {{ background: var(--black); color: var(--white); font-family: 'Share Tech Mono', monospace; padding: 2rem; -webkit-font-smoothing: antialiased; }}
    h1 {{ font-family: 'Bebas Neue', sans-serif; font-size: clamp(2.5rem, 10vw, 4rem); color: var(--white); letter-spacing: 0.05em; line-height: 1; }}
    h1 span {{ color: var(--ember); }}
    .subtitle {{ font-family: 'Crimson Pro', serif; font-style: italic; font-weight: 300; color: var(--silver); font-size: clamp(1rem, 2vw, 1.3rem); margin: 0.5rem 0 1.5rem; max-width: 60ch; }}
    .flame-line {{ height: 2px; background: linear-gradient(90deg, transparent, var(--ember), var(--flame), var(--ember), transparent); margin: 1rem 0 2rem; }}
    .dw-nav {{ border-bottom: 1px solid rgba(255,255,255,0.08); padding: 16px 0; display: flex; align-items: center; gap: 32px; margin-bottom: 2rem; flex-wrap: wrap; }}
    .dw-nav .logo {{ font-family: 'Share Tech Mono', monospace; font-size: 18px; font-weight: 700; color: var(--white); text-decoration: none; letter-spacing: 0.05em; }}
    .dw-nav .logo span {{ color: var(--ember); }}
    .dw-nav a:not(.logo) {{ font-family: 'Share Tech Mono', monospace; font-size: 12px; text-decoration: none; color: var(--ash); letter-spacing: 0.08em; text-transform: uppercase; }}
    .dw-nav a:not(.logo):hover {{ color: var(--white); }}
    .download-row {{ margin: 0 0 2rem; }}
    .download-row a {{ display: inline-block; font-family: 'Bebas Neue', sans-serif; font-size: 1.2rem; letter-spacing: 0.1em; color: var(--white); background: var(--ember); padding: 0.6rem 1.8rem; text-decoration: none; transition: background 0.2s; }}
    .download-row a:hover {{ background: var(--flame); }}
    .download-row .hint {{ color: var(--ash); font-size: 0.65rem; letter-spacing: 0.1em; margin-top: 0.6rem; }}
    .section-head {{ font-family: 'Bebas Neue', sans-serif; font-size: 1.6rem; letter-spacing: 0.1em; color: var(--ember); margin: 2.5rem 0 1rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1px; background: var(--iron); border: 1px solid var(--iron); }}
    a.maker {{ background: var(--steel); padding: 0.9rem 1.2rem; text-decoration: none; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; transition: background 0.15s; }}
    a.maker:hover {{ background: var(--iron); }}
    .mname {{ font-family: 'Bebas Neue', sans-serif; font-size: 1.15rem; letter-spacing: 0.04em; color: var(--white); }}
    .badge {{ font-size: 0.5rem; letter-spacing: 0.12em; text-transform: uppercase; white-space: nowrap; }}
    .badge.official {{ color: var(--flame); }}
    .badge.search {{ color: var(--ash); }}
    .collab {{ background: var(--steel); padding: 0.9rem 1.2rem; border-left: 3px solid var(--ember); font-family: 'Bebas Neue', sans-serif; font-size: 1.05rem; color: var(--ember); letter-spacing: 0.04em; }}
    footer {{ margin-top: 3rem; color: var(--ash); font-size: 0.65rem; letter-spacing: 0.3em; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }}
    .hgr {{ font-family: 'Bebas Neue', sans-serif; color: var(--ember); font-size: 1.2rem; }}
  </style>
</head>
<body>
  <h1>OUR COOL <span>MAKERS</span></h1>
  <p class="subtitle">Every maker Drop Watcher follows, in one list — {total} names, including our Blade Show 2026 additions.
    Save it, bookmark it, chase the grails yourself.</p>
  <div class="flame-line"></div>

  <nav class="dw-nav">
    <a href="/" class="logo">DROP <span>WATCHER</span></a>
    <a href="/">Home</a>
    <a href="/what-we-watch.html">What We Watch</a>
    <a href="/watchlist.html">Watch</a>
    <a href="/alerts.html">Alerts</a>
    <a href="/stats.html">Stats</a>
  </nav>

  <div class="download-row">
    <a href="/our-cool-makers.html" download="our-cool-makers.html">⬇ DOWNLOAD THIS LIST</a>
    <div class="hint">Saves this page to your machine. Links open the maker's official site where we have one, otherwise a quick search.</div>
  </div>

{sections}
  <footer>
    <span>INSTOCKORNOT.CLUB · WE WATCH KNIVES · YOU CAN WATCH ANYTHING</span>
    <span class="hgr">HGR</span>
  </footer>
</body>
</html>
"""


def main():
    html = render()
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, 'w') as f:
        f.write(html)
    print(f"wrote {OUT_FILE} ({len(html)} bytes)")


if __name__ == '__main__':
    main()
