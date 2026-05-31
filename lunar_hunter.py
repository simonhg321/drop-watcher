# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
lunar_hunter.py — a bespoke, hard-charging hunt for ONE grail:
the Chris Reeve "Lunar Landing" CGG graphic (the first man on the moon).

Why this isn't a normal watch
  The Lunar Landing is a rare Computer-Generated Graphic — it surfaces sporadically
  across many CRK dealers, sells in minutes, and is often listed even while sold out.
  A single-URL keyword watch would miss it. So this hunts a curated fleet of CRK
  dealers every run, deep-links the exact product when the dealer exposes a structured
  catalog, and alerts Simon directly the instant ANY listing appears — in stock OR not,
  because knowing one exists is half the battle.

Tiers
  • shopify  — products.json catalog → we know per-item URL + live stock → DEEP LINK.
  • text     — non-Shopify dealer page; we scan the rendered text for the signal and
               link to the page (no per-item URL available).

Known blind spot (stated, not hidden): Blade HQ, KnifeCenter and GP Knives hard-block
non-browser scrapers (HTTP 403), so they can't be auto-scanned from here.

Run
  cron:  */8 * * * * python3 /home/shg/drop-watcher/lunar_hunter.py
  arm:   python3 /home/shg/drop-watcher/lunar_hunter.py --arm   (sends a "hunt is live"
         confirmation email so you can see the rig before it ever fires)
HGR
"""

import os
import sys
import re
import html as html_mod
import hashlib
import logging

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))

import paths
import db
import collection_fetch
from alerter import send_email

# ── Who & how often ───────────────────────────────────────────────────────────
HUNTER_EMAIL   = os.environ.get('DW_LUNAR_EMAIL') or os.environ.get('ALERT_TO')
SEEN_TTL_HOURS = 24 * 14   # re-alert at most every 2 weeks for the SAME find/state

# The signal. "lunar landing" is the canonical CGG name; the rest are safety nets.
# All matching happens inside CRK-scoped pages, so these stay specific in practice.
LUNAR_SIGNALS = ['lunar landing', 'lunar', 'moon landing', 'first man on the moon', 'apollo']

# ── The fleet (verified live 2026-05-31) ──────────────────────────────────────
SOURCES = [
    {'name': 'KnifeJoy',         'url': 'https://www.knifejoy.com/collections/chris-reeve-knives'},
    {'name': 'Northwest Knives', 'url': 'https://northwestknives.com/collections/chris-reeve-knives'},
    {'name': 'Southern Edges',   'url': 'https://southernedges.com/collections/chris-reeve-knives'},
    {'name': 'DLT Trading',      'url': 'https://www.dlttrading.com/chris-reeve-knives'},
]
BLIND_SPOTS = ['Blade HQ', 'KnifeCenter', 'GP Knives']  # 403 bot-block — can't auto-scan

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [lunar_hunter] %(levelname)s %(message)s',
    handlers=[logging.FileHandler(os.path.join(paths.LOG_DIR, 'lunar_hunter.log')),
              logging.StreamHandler()]
)
log = logging.getLogger('lunar_hunter')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; personal use)'}
MAX_RESPONSE_BYTES = 3 * 1024 * 1024


def fetch_page(url, ssl_permissive=False):
    """Minimal fetch_page compatible with collection_fetch (size-capped, never raises)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True,
                         verify=not ssl_permissive)
        r.raise_for_status()
        content = r.content[:MAX_RESPONSE_BYTES]
        r.close()
        return content.decode('utf-8', errors='replace')
    except requests.RequestException as e:
        log.warning(f"fetch failed {url}: {e}")
        return None


def _signal_in(text):
    t = (text or '').lower()
    return [s for s in LUNAR_SIGNALS if s in t]


def scan_source(src):
    """Return a list of finds for one dealer.

    Shopify dealers yield per-product finds (title, url, in_stock). Text-scan dealers
    yield at most one page-level find linking to the collection.
    """
    text, products = collection_fetch.fetch_collection(src['url'], fetch_page, log=log)
    if text is None:
        log.warning(f"{src['name']} — unreachable")
        return []

    finds = []
    if products:  # Shopify → deep-link each matching product
        for p in products:
            blob = (p.get('title', '') + ' ' + ' '.join(p.get('tags') or [])
                    + ' ' + p.get('url', ''))
            if _signal_in(blob):
                finds.append({
                    'source':   src['name'],
                    'title':    p.get('title', '') or 'Chris Reeve Lunar Landing',
                    'url':      p.get('url', '') or src['url'],
                    'in_stock': bool(p.get('available')),
                    'price':    p.get('price', ''),
                    'deep':     True,
                })
    else:  # text-scan → one page-level find if the signal is anywhere on the page
        if _signal_in(text):
            finds.append({
                'source':   src['name'],
                'title':    'Chris Reeve Lunar Landing (listed on page)',
                'url':      src['url'],
                'in_stock': None,           # unknown from text scan
                'price':    '',
                'deep':     False,
            })
    if finds:
        log.info(f"{src['name']} — 🌙 {len(finds)} LUNAR find(s)")
    else:
        log.info(f"{src['name']} — no lunar")
    return finds


def _seen_key(find):
    # Keyed on source + url + stock state, so a sold-out→in-stock flip re-alerts.
    raw = f"lunar:{find['source']}|{find['url']}|{find['in_stock']}"
    return hashlib.md5(raw.encode()).hexdigest()


# ── The (deliberately over-built) email ───────────────────────────────────────
def _shell(inner):
    return f"""
    <div style="font-family:'Courier New',monospace;background:#05070d;color:#dfe6f2;
                padding:0;max-width:600px;border:1px solid #1b2740;">
      <div style="background:linear-gradient(135deg,#0b1226 0%,#1a2347 55%,#05070d 100%);
                  padding:28px 24px;border-bottom:1px solid #243357;text-align:center;">
        <div style="font-size:40px;line-height:1;">🌙</div>
        <div style="color:#9fb4e8;font-size:11px;letter-spacing:0.35em;margin-top:10px;">
          DROP WATCHER · GRAIL PROTOCOL</div>
        <div style="color:#fff;font-size:20px;letter-spacing:0.12em;margin-top:6px;">
          LUNAR LANDING</div>
        <div style="color:#5f7099;font-size:10px;letter-spacing:0.2em;margin-top:6px;">
          CHRIS REEVE · COMPUTER-GENERATED GRAPHIC</div>
      </div>
      <div style="padding:24px;">{inner}</div>
      <div style="padding:16px 24px;border-top:1px solid #1b2740;color:#46557a;font-size:10px;
                  letter-spacing:0.15em;">
        instockornot.club · bespoke single-grail hunt · armed for Simon
      </div>
    </div>"""


def build_find_email(finds):
    rows = ''
    for f in finds:
        if f['in_stock'] is True:
            badge = '<span style="color:#0a0a0a;background:#39d98a;padding:2px 8px;font-size:10px;letter-spacing:0.1em;">IN STOCK</span>'
        elif f['in_stock'] is False:
            badge = '<span style="color:#fff;background:#7a3b3b;padding:2px 8px;font-size:10px;letter-spacing:0.1em;">SOLD OUT</span>'
        else:
            badge = '<span style="color:#0a0a0a;background:#caa54b;padding:2px 8px;font-size:10px;letter-spacing:0.1em;">LISTED</span>'
        price = f' <span style="color:#5f7099">— ${html_mod.escape(str(f["price"]))}</span>' if f['price'] else ''
        cta = 'GO →' if f['deep'] else 'OPEN PAGE →'
        rows += f"""
        <div style="background:#0b101f;border:1px solid #1f2c4a;padding:16px;margin:0 0 12px;">
          <div style="color:#7f93c4;font-size:10px;letter-spacing:0.2em;">{html_mod.escape(f['source'])} &nbsp; {badge}</div>
          <div style="color:#fff;font-size:14px;margin:8px 0;">{html_mod.escape(f['title'])}{price}</div>
          <a href="{html_mod.escape(f['url'])}" style="background:#3a5bd9;color:#fff;padding:9px 18px;
             text-decoration:none;font-size:11px;letter-spacing:0.15em;">{cta}</a>
        </div>"""
    n = len(finds)
    inner = (f'<p style="color:#dfe6f2;font-size:14px;">Simon — the hunt hit. '
             f'<b style="color:#fff;">{n} Lunar Landing listing'
             f'{"s" if n != 1 else ""}</b> surfaced. Move fast.</p>{rows}'
             f'<p style="color:#46557a;font-size:11px;margin-top:18px;">'
             f'Blind spots (bot-blocked, check by hand): {", ".join(BLIND_SPOTS)}.</p>')
    subj = f"🌙 LUNAR LANDING FOUND — {n} listing{'s' if n != 1 else ''} ({finds[0]['source']}…)"
    txt_lines = [f"- [{('IN STOCK' if f['in_stock'] else 'SOLD OUT' if f['in_stock'] is False else 'LISTED')}] "
                 f"{f['source']}: {f['title']}{(' — $'+str(f['price'])) if f['price'] else ''}\n  {f['url']}"
                 for f in finds]
    txt = ("LUNAR LANDING — Chris Reeve CGG — FOUND\n\n" + "\n".join(txt_lines) +
           f"\n\nBlind spots (check by hand): {', '.join(BLIND_SPOTS)}\n"
           "instockornot.club bespoke grail hunt")
    return subj, _shell(inner), txt


def _short_url(url):
    return re.sub(r'^https?://(www\.)?', '', url)


def build_armed_email():
    fleet = ''.join(f'<li style="margin:4px 0;color:#bccaeb">{html_mod.escape(s["name"])}'
                    f' <span style="color:#46557a">— {html_mod.escape(_short_url(s["url"]))}</span></li>'
                    for s in SOURCES)
    inner = (f'<p style="color:#dfe6f2;font-size:14px;">The Lunar Landing hunt is '
             f'<b style="color:#39d98a;">ARMED</b> and running every 8 minutes.</p>'
             f'<div style="background:#0b101f;border:1px solid #1f2c4a;padding:16px;margin:16px 0;">'
             f'<div style="color:#7f93c4;font-size:10px;letter-spacing:0.2em;margin-bottom:8px;">'
             f'FLEET UNDER WATCH</div><ul style="margin:0;padding-left:18px">{fleet}</ul></div>'
             f'<p style="color:#dfe6f2;font-size:13px;">Deep-link dealers report the exact '
             f'item + live stock. The instant a Lunar Landing appears — in stock or sold out — '
             f'you get a hit.</p>'
             f'<p style="color:#46557a;font-size:11px;margin-top:14px;">Known blind spots '
             f'(bot-blocked, not auto-scanned): {", ".join(BLIND_SPOTS)}.</p>')
    return "🌙 Lunar Landing hunt is ARMED", _shell(inner), (
        "Lunar Landing hunt ARMED — running every 8 min.\n\nFleet: "
        + ", ".join(s['name'] for s in SOURCES)
        + f"\nBlind spots (bot-blocked): {', '.join(BLIND_SPOTS)}\n")


def run():
    log.info("Lunar hunt starting — HGR")
    all_finds = []
    for src in SOURCES:
        try:
            all_finds.extend(scan_source(src))
        except Exception as e:
            log.error(f"{src['name']} — scan error: {e}")

    fresh = []
    for f in all_finds:
        key = _seen_key(f)
        if db.is_feed_seen(key, hours=SEEN_TTL_HOURS):
            log.info(f"already alerted: {f['source']} / {f['in_stock']}")
            continue
        fresh.append((f, key))

    if not fresh:
        log.info(f"Hunt done — {len(all_finds)} find(s), none fresh.")
        return

    subj, html, txt = build_find_email([f for f, _ in fresh])
    if send_email(subj, html, txt, to_addr=HUNTER_EMAIL):
        for _, key in fresh:
            db.mark_feed_seen(key)
        log.info(f"🌙 ALERT SENT — {len(fresh)} fresh Lunar find(s) to {HUNTER_EMAIL}")
    else:
        log.error("send_email failed — not marking seen, will retry next run")


def arm():
    subj, html, txt = build_armed_email()
    ok = send_email(subj, html, txt, to_addr=HUNTER_EMAIL)
    log.info(f"Armed notice sent: {ok}")


if __name__ == '__main__':
    if '--arm' in sys.argv:
        arm()
    else:
        run()
