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
import base64
import html as html_mod
import hashlib
import logging

import requests
import feedparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))

import paths
import db
import collection_fetch
import safe_fetch
from alerter import send_email
from sms_alerter import _send_twilio_sms

# ── Who & how often ───────────────────────────────────────────────────────────
HUNTER_EMAIL   = os.environ.get('DW_LUNAR_EMAIL') or os.environ.get('ALERT_TO')
HUNTER_PHONE   = os.environ.get('DW_LUNAR_PHONE')   # E.164, e.g. +13472766172; SMS skipped if unset
SEEN_TTL_HOURS = 24 * 14   # re-alert at most every 2 weeks for the SAME find/state

# The grail roster (S60: generalized from the single Lunar Landing hunt).
# Per grail: an `exact` phrase always fires; bare `signals` fire on CRK-SCOPED
# dealer pages, but on UNSCOPED pages (whole-store pre-owned catalogs, Reddit,
# eBay — mixed makers) they ALSO need Chris Reeve context in the same blob:
# "lunar"/"apollo" are also CRKT/Civivi model names, and "cross hatch" is a
# handle texture on Jack Wolf knives (the S60 false positive).
REEVE_CONTEXT = ['reeve', 'crk', 'sebenza', 'inkosi', 'mnandi', 'impinda', 'umnumzaan']

GRAILS = [
    {
        'key': 'lunar', 'display': 'Lunar Landing', 'emoji': '🌙',
        'subtitle': 'CHRIS REEVE · COMPUTER-GENERATED GRAPHIC',
        'exact': ['lunar landing'],
        'signals': ['lunar landing', 'lunar', 'moon landing', 'first man on the moon', 'apollo'],
        'ebay_query': 'chris reeve lunar landing',
    },
    {
        'key': 'crosshatch', 'display': 'Inkosi Cross Hatch', 'emoji': '⚔️',
        'subtitle': 'CHRIS REEVE · CROSS HATCH GRAPHIC',
        'exact': ['inkosi cross hatch'],
        'signals': ['cross hatch', 'crosshatch', 'cross-hatch'],
        'ebay_query': 'chris reeve cross hatch',
    },

    # ── The CRK grail gamut (S70) ─────────────────────────────────────────────
    # The S+A tiers of Simon's CRK_grail_gamut.csv (lives in ~, not this repo),
    # hand-curated into entries: bare model names only where the word is safe on
    # a knife page (no bare "sebenza"/"mnandi"/"umnumzaan" — those name current
    # production). ORDER MATTERS: the scan loop stops at the first grail a
    # product matches, so specific variants sit above generic catch-alls
    # (sebenza_25 before damascus, original before regular, prototype/d2 last).
    # `est_market` is display-only context in the alert — never a gate: an
    # overpriced listing still alerts, Simon judges the ask.
    # NO ebay_query on any of these — Sky owns the eBay work; scan_ebay skips
    # grails without a query. Excluded rows: Yarborough (Simon: respect, don't
    # chase), all B/C tiers, Umnumzaan first-gen (sellers don't label gens).
    {
        'key': 'original_sebenza', 'display': 'Original Sebenza', 'emoji': '🏛️',
        'subtitle': 'CHRIS REEVE · PRE-REGULAR FLAT HANDLE 1991–96',
        'exact': ['original sebenza'],
        'signals': ['original sebenza', 'pre-regular sebenza', 'flat handle sebenza'],
        'est_market': '$2,500–6,000+',
    },
    {
        'key': 'sebenza_25', 'display': 'Sebenza 25', 'emoji': '🎯',
        'subtitle': 'CHRIS REEVE · THE 2012–16 WINDOW',
        'exact': [],
        'signals': ['sebenza 25', '25 sebenza', 'large sebenza 25', 'small sebenza 25'],
        'est_market': '$900–3,000+ (Damascus/inlay top the band)',
    },
    {
        'key': 'regular_sebenza', 'display': 'Regular Sebenza', 'emoji': '📐',
        'subtitle': 'CHRIS REEVE · SLANTED LINES, BG-42 ERA',
        'exact': [],
        'signals': ['regular sebenza', 'sebenza regular', 'bg-42', 'bg42',
                    'ats-34', 'ats 34'],
        'est_market': '$1,000–2,500 (BG-42 premium)',
    },
    {
        'key': 'anniversary_21', 'display': 'Sebenza 21st Anniversary', 'emoji': '🎖️',
        'subtitle': 'CHRIS REEVE · 2009 NUMBERED RUN',
        'exact': [],
        'signals': ['21st anniversary'],
        'est_market': '$1,200–2,200',
    },
    {
        'key': 'unique_graphic', 'display': 'Unique Graphic', 'emoji': '🎨',
        'subtitle': 'CHRIS REEVE · UG / CGG / ANNUAL GRAPHICS',
        'exact': ['unique graphic'],
        'signals': ['unique graphic', 'cgg', 'computer generated graphic'],
        # Current-production catalog UGs (the Night Sky 31 run — 212 matches at
        # KnifeJoy alone on the first live check) are NOT the grail one-of-ones.
        'veto': ['sebenza 31', 'night sky'],
        'est_market': '$900–5,000+ (one-of-ones top the band)',
    },
    {
        'key': 'ti_lock', 'display': 'Ti-Lock', 'emoji': '🔩',
        'subtitle': 'CHRIS REEVE · HAWK COLLAB 2010–17',
        'exact': [],
        'signals': ['ti-lock', 'ti lock', 'tilock'],
        'est_market': '$1,200–2,500 (protos $3,000–8,000+)',
    },
    {
        'key': 'mammoth', 'display': 'Mammoth Inlay', 'emoji': '🦣',
        'subtitle': 'CHRIS REEVE · MAMMOTH IVORY / BARK INLAY',
        'exact': [],
        'signals': ['mammoth', 'ivory'],
        'est_market': '$1,000–2,200 (check WA ivory rules)',
    },
    {
        'key': 'jereboam', 'display': 'Jereboam', 'emoji': '🗿',
        'subtitle': 'CHRIS REEVE · SA-ERA ONE-PIECE MK I/II',
        # CRK spells it Jereboam (the wine bottle is jeroboam) → safe as exact.
        'exact': ['jereboam'],
        'signals': ['jereboam'],
        'est_market': '$1,000–2,500 (SA serials; ignore fantasy asks)',
    },
    {
        'key': 'shadow_op', 'display': 'Shadow One-Piece', 'emoji': '🌑',
        'subtitle': 'CHRIS REEVE · SA-ERA SPEARPOINT',
        'exact': [],
        'signals': ['shadow'],
        'est_market': '$1,000–2,200 (SA serials only)',
    },
    {
        'key': 'project', 'display': 'Project I/II', 'emoji': '🚀',
        'subtitle': 'CHRIS REEVE · THE ONE-PIECE ICON',
        'exact': [],
        'signals': ['project'],
        'est_market': '$700–1,500 (early serials carry the premium)',
    },
    {
        'key': 'mk_series', 'display': 'MK-Series One-Piece', 'emoji': '⚙️',
        'subtitle': 'CHRIS REEVE · MK IV / V / VI',
        'exact': [],
        'signals': ['mk iv', 'mk v', 'mk vi', 'mk 4', 'mk 5', 'mk 6',
                    'mark iv', 'mark v', 'mark vi'],
        'est_market': '$600–2,000 (MK IV tops the band)',
    },
    {
        'key': 'aviator', 'display': 'Aviator', 'emoji': '✈️',
        'subtitle': 'CHRIS REEVE · ONE-PIECE SAWBACK',
        'exact': [],
        'signals': ['aviator'],
        'est_market': '$500–1,200 (5in run of 50: $2,000–4,000+, unicorn)',
    },
    {
        'key': 'sable', 'display': 'Sable IV', 'emoji': '🦌',
        'subtitle': 'CHRIS REEVE · RECURVE ONE-PIECE',
        'exact': [],
        'signals': ['sable'],
        'est_market': '$600–1,300',
    },
    {
        'key': 'impofu', 'display': 'Impofu', 'emoji': '🔪',
        'subtitle': 'CHRIS REEVE · SHORT-RUN SKINNER ~2019–21',
        'exact': ['impofu'],
        'signals': ['impofu'],
        'est_market': '$400–800 (sleeper)',
    },
    # Catch-alls last — anything more specific above wins the match first.
    {
        'key': 'damascus', 'display': 'Damascus CRK', 'emoji': '🌊',
        'subtitle': 'CHRIS REEVE · DEVIN THOMAS / CHAD NICHOLS',
        'exact': [],
        'signals': ['damascus'],
        # Damascus 31s/Inkosis are current catalog stock (125 matches at
        # KnifeJoy on the first live check) — the grail band is the 21/Regular
        # Devin Thomas era. The CSV tiers 31s as the C control group.
        'veto': ['sebenza 31', 'inkosi'],
        'est_market': '$900–3,500 (Regular + Damascus tops the band)',
    },
    {
        'key': 'd2_run', 'display': 'D2 One-Piece Run', 'emoji': '🧱',
        'subtitle': 'CHRIS REEVE · LIMITED D2 (A2 WAS STANDARD)',
        'exact': [],
        'signals': ['d2'],
        'est_market': 'A2 price +30–50%',
    },
    {
        'key': 'prototype', 'display': 'CRK Prototype', 'emoji': '🧪',
        'subtitle': 'CHRIS REEVE · SHOP-MARKED / ONE-OFF',
        'exact': [],
        'signals': ['prototype', 'pre-production', 'one of one', 'one-off'],
        'est_market': 'market-maker — demand documentation',
    },
]
# Pre-compile the word-boundary patterns once — matching runs per product
# (up to ~750/dealer × 14 dealers every 8 min), so recompiling per call was waste.
_REEVE_CONTEXT_RE = [re.compile(r'\b' + re.escape(c) + r'\b') for c in REEVE_CONTEXT]
for _g in GRAILS:
    _g['_signal_re'] = [re.compile(r'\b' + re.escape(s) + r'\b') for s in _g['signals']]
    _g['_veto_re'] = [re.compile(r'\b' + re.escape(v) + r'\b') for v in _g.get('veto', [])]

# ── The dealer fleet ──────────────────────────────────────────────────────────
# scoped:True  → page is already filtered to Chris Reeve, so any lunar signal fires.
# scoped:False → general/secondary-market page, so a match ALSO needs Reeve context.
SOURCES = [
    # CRK-scoped dealer collections (verified live 2026-05-31)
    {'name': 'KnifeJoy',         'url': 'https://www.knifejoy.com/collections/chris-reeve-knives', 'scoped': True},
    {'name': 'Northwest Knives', 'url': 'https://northwestknives.com/collections/chris-reeve-knives', 'scoped': True},
    {'name': 'Southern Edges',   'url': 'https://southernedges.com/collections/chris-reeve-knives', 'scoped': True},
    {'name': 'DLT Trading',      'url': 'https://www.dlttrading.com/chris-reeve-knives', 'scoped': True},

    # CRK dealers promoted by dealer_scout, added 2026-06-01 (all CRK-scoped pages).
    {'name': 'Edgeworks',        'url': 'https://edgeworksonline.com/collections/chris-reeve-knives', 'scoped': True},  # Shopify deep-link
    {'name': "St Nick's Knives", 'url': 'https://stnicksknives.com/collections/chris-reeve-knives', 'scoped': True},   # Shopify deep-link
    {'name': 'Sooner State',     'url': 'https://soonerstateknives.com/chrisreevefoldingknives.htm', 'scoped': True},  # static HTML → text-scan

    # The 17-dealer SHARP_SOURCE S59 CRK-authorized-dealer audit (config/sources.yaml),
    # added 2026-06-30 — none of these were ever in the grail fleet. Each verified live
    # with a real CRK-filtered page where one exists; scoped:False falls back to the
    # store root + Reeve-context match where no dedicated CRK page was found.
    {'name': 'Blade Ops',            'url': 'https://bladeops.com/chris-reeve-knives/', 'scoped': True},
    {'name': 'Knifeworks',           'url': 'https://knifeworks.com/', 'scoped': False},
    {'name': 'Pure Blades',          'url': 'https://pureblades.com/chris-reeve/', 'scoped': True},
    {'name': 'JT Knives',            'url': 'https://www.jtknives.com/Chris-Reeve-Knives_c_12.html', 'scoped': True},
    {'name': 'True North Knives',    'url': 'https://www.truenorthknives.com/vcom/chris-reeve-knives-c-939.html', 'scoped': True},
    {'name': 'Knives Plus',          'url': 'https://www.knivesplus.com/chris-reeve-knives-crk.html', 'scoped': True},
    {'name': 'Castle Gate',          'url': 'https://www.castlegate.com/brands/chris-reeve-knives/', 'scoped': True},
    {'name': 'Deepak Chopra Inc',    'url': 'https://www.deepakc.com/brands/chris-reeve-knives.html', 'scoped': True},
    {'name': 'Revolver Tactical',    'url': 'https://www.revolvertactical.com/product-category/all-products/chris-reeve-knives/', 'scoped': True},
    {'name': 'Claytons Range',       'url': 'https://claytonsrangepa.com/', 'scoped': False},
    {'name': "Martin's Firearms",    'url': 'https://martinscf.com/chris-reeve-knives/', 'scoped': True},
    {'name': "Little Joe's Boots",   'url': 'https://littlejoesboots.net/', 'scoped': False},
    {'name': 'Ski Mania',            'url': 'https://stores.theeouterlimit.com/knives/', 'scoped': False},
    {'name': 'Ye Ole Cutlery',       'url': 'https://mdggifts.com/Chris-Reeve-Knives_bymfg_420-4-1.html', 'scoped': True},
    {'name': 'Fred Eisen Art Knives', 'url': 'https://www.artknives.com/art-knives/chris-reeve-knives/', 'scoped': True},
    {'name': '1911 Custom Solutions', 'url': 'https://www.1911customsolutions.com/', 'scoped': False},

    # Knife Art — not in sources.yaml's S59 list but carries deep CRK inventory on a
    # dedicated static page with per-item "In Stock" markers (verified 2026-06-30).
    {'name': 'Knife Art',            'url': 'https://www.knifeart.com/chrisreeve.html', 'scoped': True},

    # AGC Firearms — general gun-store dropship catalog, requested by Simon 2026-07-01.
    # No CRK on page 1 at add time (Pro-Tech Knives currently) — unscoped watch in case
    # their distributor feed rotates in Chris Reeve stock later.
    {'name': 'AGC Firearms',         'url': 'https://agcfirearms.com/product-groups/knives', 'scoped': False},

    # Secondary market / pre-owned (added 2026-06-01 from what-we-watch.html → sources.yaml).
    # Whole-store pre-owned pages, NOT CRK-filtered → scoped:False (Reeve context required).
    {'name': 'Recon 1 — CRK',           'url': 'https://recon1.com/collections/chris-reeve-knives', 'scoped': True},  # old /collections/pre-owned slug 404s (site re-platformed); this one verified live 2026-06-30
    {'name': 'eKnives — Pre-Owned',     'url': 'https://eknives.com/preowned/', 'scoped': False},
    {'name': 'Knife Purveyor',          'url': 'https://www.knifepurveyor.com', 'scoped': False},
    {'name': 'Luv Them Knives',         'url': 'https://luvthemknives.com/collections/pre-owned-knives', 'scoped': False},
    {'name': 'Rivers Edge — Consignment', 'url': 'https://riversedgecutlery.com/consignment-shop/', 'scoped': False},
    {'name': 'EDC Lifestyle — Pre-Owned', 'url': 'https://www.edclifestyle.com/pre-owned-consignment/', 'scoped': False},
    {'name': 'Knife Market',            'url': 'https://knife-market.com', 'scoped': False},
    {'name': 'Cutting Edge — Pre-Owned', 'url': 'https://cuttingedge.com', 'scoped': False},

    # Consignment/flip marketplaces, added 2026-06-30 — confirmed carrying CRK secondary
    # stock at audit time (inventory turns daily, so scoped:False + Reeve context is the
    # right safety net rather than a fixed CRK collection URL).
    {'name': 'Arizona Custom Knives — Recently Added', 'url': 'https://www.arizonacustomknives.com/recently-added/', 'scoped': False},
    {'name': 'Urban EDC',               'url': 'https://urbanedc.com/collections/in-stock-knives', 'scoped': False},  # rebranded from urbanedcsupply.com, old domain 301s here
]
# Reddit buy/sell/trade subs — a grail often hits the secondary market before dealers.
# Reddit blocks search + r/knifeswap from this host, but these plain feeds work (verified).
# r/crk is the dedicated Chris Reeve sub: every post is Reeve-context, so a bare "lunar"
# matches there (the sub name is fed into the match blob), while the general swap subs
# keep the strict lunar+Reeve rule.
REDDIT_SUBS = ['crk', 'knife_swap', 'EDCexchange', 'bladesinstock']

BLIND_SPOTS = ['Blade HQ', 'KnifeCenter', 'GP Knives', 'Reddit search/r-knifeswap (403)',
               "Helacious Blades (AWS WAF challenges our UA specifically, verified 2026-06-30)"]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [lunar_hunter] %(levelname)s %(message)s',
    handlers=[logging.FileHandler(os.path.join(paths.LOG_DIR, 'lunar_hunter.log')),
              logging.StreamHandler()]
)
log = logging.getLogger('lunar_hunter')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; +https://instockornot.club; instockornot)'}
MAX_RESPONSE_BYTES = 3 * 1024 * 1024

# ── eBay Browse API ─────────────────────────────────────────────────────────
# The authenticated API path — NOT the scraper path that 403s from this datacenter
# IP on /itm/ and /sch/ pages. Dormant until creds are set (mirrors the SMS skip):
# create a free Production app at developer.ebay.com → set DW_EBAY_CLIENT_ID +
# DW_EBAY_CLIENT_SECRET in /etc/drop-watcher/.env, no code change to go live.
EBAY_TOKEN_URL  = 'https://api.ebay.com/identity/v1/oauth2/token'
EBAY_SEARCH_URL = 'https://api.ebay.com/buy/browse/v1/item_summary/search'
EBAY_SCOPE      = 'https://api.ebay.com/oauth/api_scope'
EBAY_QUERY      = 'chris reeve lunar landing'


def fetch_page(url, ssl_permissive=False):
    """SSRF-guarded, size-capped fetch (never raises) — shared impl in safe_fetch."""
    return safe_fetch.fetch_text(url, max_bytes=MAX_RESPONSE_BYTES,
                                 ssl_permissive=ssl_permissive, headers=HEADERS, log=log)


def _grail_match(grail, text, scoped):
    """Does this blob name the grail?

    An exact phrase always wins. Otherwise a bare signal only counts on a
    CRK-SCOPED page (scoped=True). On an UNSCOPED page (a whole-store pre-owned
    catalog, Reddit, eBay) we also require Chris Reeve context in the SAME blob.
    Reeve terms match on word boundaries so 'crk' does NOT match 'CRKT'.
    A veto term kills the match outright — even an exact hit — so grails whose
    name collides with a current-production run (S70: 'unique graphic' vs the
    catalog Night Sky 31s) don't flood the alerts."""
    t = (text or '').lower()
    if any(p.search(t) for p in grail.get('_veto_re', [])):
        return False
    if any(e in t for e in grail['exact']):
        return True
    if not any(p.search(t) for p in grail['_signal_re']):
        return False
    if scoped:
        return True
    return any(p.search(t) for p in _REEVE_CONTEXT_RE)


def _lunar_match(text, scoped):
    """Back-compat shim: the original single-grail matcher (eBay default path)."""
    return _grail_match(GRAILS[0], text, scoped)


def scan_reddit():
    """Scan buy/sell/trade subreddit feeds for a Lunar Landing listing.

    Uses the plain r/<sub>.rss feed (the same method feed_watcher uses — Reddit blocks
    search + r/knifeswap from this host, but these feeds work). Each new post's title +
    summary is matched; a hit links straight to the Reddit permalink.
    """
    finds = []
    for sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}.rss"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            feed = feedparser.parse(r.text)
        except Exception as e:
            log.warning(f"Reddit r/{sub} — feed fetch failed: {e}")
            continue
        hits = 0
        for entry in feed.entries:
            # Include the sub name so r/crk counts as Reeve-context automatically.
            blob = f"{sub} {entry.get('title', '')} {entry.get('summary', '')}"
            for g in GRAILS:
                # Reddit posts span all makers → unscoped (Reeve context required).
                if _grail_match(g, blob, scoped=False):
                    finds.append({
                        'source':   f"Reddit r/{sub}",
                        'title':    entry.get('title', f"{g['display']} post")[:140],
                        'url':      entry.get('link', url),
                        'in_stock': None,        # it's a listing, not dealer stock
                        'price':    '',
                        'deep':     True,
                        'grail':    g,
                    })
                    hits += 1
                    break
        log.info(f"Reddit r/{sub} — {len(feed.entries)} posts, {hits} grail match(es)")
    return finds


def _ebay_active():
    """True when both eBay API creds are present — i.e. the eBay scanner is live
    (vs. dormant). Used by scan_ebay and the armed-notice fleet list."""
    return bool(os.environ.get('DW_EBAY_CLIENT_ID') and os.environ.get('DW_EBAY_CLIENT_SECRET'))


def _ebay_token(client_id, client_secret):
    """Fetch an eBay application access token (client-credentials grant).

    Returns the token string, or None on any failure (never raises — one bad eBay
    call must not abort the hunt)."""
    try:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        r = requests.post(
            EBAY_TOKEN_URL,
            headers={'Authorization': f'Basic {basic}',
                     'Content-Type': 'application/x-www-form-urlencoded'},
            data={'grant_type': 'client_credentials', 'scope': EBAY_SCOPE},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get('access_token')
    except Exception as e:
        log.warning(f"eBay — token fetch failed: {e}")
        return None


def _ebay_search(token, query=None):
    """Query the Browse API for one grail, newest first. Returns the raw
    itemSummaries list (or [] on any failure)."""
    try:
        r = requests.get(
            EBAY_SEARCH_URL,
            headers={'Authorization': f'Bearer {token}',
                     'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'},
            params={'q': query or EBAY_QUERY, 'sort': 'newlyListed', 'limit': 50},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get('itemSummaries') or []
    except Exception as e:
        log.warning(f"eBay — search failed: {e}")
        return []


def _ebay_finds_from_summaries(summaries, grail=None):
    """Map Browse API item summaries → find dicts, keeping only true grail
    listings. eBay best-match is fuzzy, so each title is re-checked with the shared
    unscoped matcher (Reeve context required) to drop unrelated knives."""
    grail = grail or GRAILS[0]
    finds = []
    for s in summaries or []:
        title = s.get('title', '') or ''
        if not _grail_match(grail, title, scoped=False):
            continue
        price = s.get('price') or {}
        finds.append({
            'source':   'eBay',
            'title':    title or f"Chris Reeve {grail['display']}",
            'url':      s.get('itemWebUrl', '') or '',
            'in_stock': None,                 # active listing != dealer stock → "LISTED"
            'price':    price.get('value', '') if isinstance(price, dict) else '',
            'deep':     True,
            'grail':    grail,
        })
    return finds


def scan_ebay():
    """Scan eBay for the Lunar Landing via the Browse API.

    Dormant when creds are unset (logs once, returns []) — same pattern as the SMS
    skip — so the rig ships inert and goes live the moment DW_EBAY_CLIENT_ID /
    DW_EBAY_CLIENT_SECRET are present in the environment."""
    if not _ebay_active():
        log.info("eBay — no DW_EBAY_CLIENT_ID/SECRET set, skipping (dormant)")
        return []

    token = _ebay_token(os.environ['DW_EBAY_CLIENT_ID'], os.environ['DW_EBAY_CLIENT_SECRET'])
    if not token:
        return []

    finds = []
    for g in GRAILS:
        # Gamut entries (S70) carry no ebay_query — Sky owns the eBay work.
        if not g.get('ebay_query'):
            continue
        summaries = _ebay_search(token, g['ebay_query'])
        g_finds = _ebay_finds_from_summaries(summaries, g)
        log.info(f"eBay [{g['key']}] — {len(summaries)} result(s), {len(g_finds)} match(es)")
        finds.extend(g_finds)
    return finds


def scan_source(src):
    """Return a list of finds for one dealer.

    Shopify dealers yield per-product finds (title, url, in_stock). Text-scan dealers
    yield at most one page-level find linking to the collection.
    """
    scoped = src.get('scoped', True)
    text, products, _candidates = collection_fetch.fetch_collection(src['url'], fetch_page, log=log)
    if text is None:
        log.warning(f"{src['name']} — unreachable")
        return []

    finds = []
    if products:  # structured products → deep-link each matching product
        for p in products:
            blob = (p.get('title', '') + ' ' + p.get('vendor', '') + ' '
                    + ' '.join(p.get('tags') or []) + ' ' + p.get('url', ''))
            for g in GRAILS:
                if _grail_match(g, blob, scoped):
                    finds.append({
                        'source':   src['name'],
                        'title':    p.get('title', '') or f"Chris Reeve {g['display']}",
                        'url':      p.get('url', '') or src['url'],
                        'in_stock': bool(p.get('available')),
                        'price':    p.get('price', ''),
                        'deep':     True,
                        'grail':    g,
                    })
                    break  # one product matches one grail
    else:  # text-scan → one page-level find per grail signalled anywhere on the page
        for g in GRAILS:
            if _grail_match(g, text, scoped):
                finds.append({
                    'source':   src['name'],
                    'title':    f"Chris Reeve {g['display']} (listed on page)",
                    'url':      src['url'],
                    'in_stock': None,           # unknown from text scan
                    'price':    '',
                    'deep':     False,
                    'grail':    g,
                })
    if finds:
        log.info(f"{src['name']} — {len(finds)} GRAIL find(s): "
                 + ', '.join(f['grail']['key'] for f in finds))
    else:
        log.info(f"{src['name']} — no grails")
    return finds


def _seen_key(find):
    # Keyed on grail + source + url + stock state, so a sold-out→in-stock flip
    # re-alerts. The 'lunar' prefix matches the original single-grail scheme so
    # existing seen-state survived the multi-grail refactor (S60).
    gkey = (find.get('grail') or GRAILS[0])['key']
    raw = f"{gkey}:{find['source']}|{find['url']}|{find['in_stock']}"
    return hashlib.md5(raw.encode()).hexdigest()


# ── The (deliberately over-built) email ───────────────────────────────────────
def _shell(inner, grail=None):
    grail = grail or GRAILS[0]
    return f"""
    <div style="font-family:'Courier New',monospace;background:#05070d;color:#dfe6f2;
                padding:0;max-width:600px;border:1px solid #1b2740;">
      <div style="background:linear-gradient(135deg,#0b1226 0%,#1a2347 55%,#05070d 100%);
                  padding:28px 24px;border-bottom:1px solid #243357;text-align:center;">
        <div style="font-size:40px;line-height:1;">{grail['emoji']}</div>
        <div style="color:#9fb4e8;font-size:11px;letter-spacing:0.35em;margin-top:10px;">
          DROP WATCHER · GRAIL PROTOCOL</div>
        <div style="color:#fff;font-size:20px;letter-spacing:0.12em;margin-top:6px;">
          {html_mod.escape(grail['display'].upper())}</div>
        <div style="color:#5f7099;font-size:10px;letter-spacing:0.2em;margin-top:6px;">
          {html_mod.escape(grail['subtitle'])}</div>
      </div>
      <div style="padding:24px;">{inner}</div>
      <div style="padding:16px 24px;border-top:1px solid #1b2740;color:#46557a;font-size:10px;
                  letter-spacing:0.15em;">
        instockornot.club · bespoke grail hunt · armed for Simon
      </div>
    </div>"""


def build_find_email(finds, grail=None):
    grail = grail or GRAILS[0]
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
    disp = grail['display']
    market = ''
    if grail.get('est_market'):
        market = (f'<p style="color:#9fb4e8;font-size:11px;letter-spacing:0.1em;">'
                  f'EST. MARKET: {html_mod.escape(grail["est_market"])}</p>')
    inner = (f'<p style="color:#dfe6f2;font-size:14px;">Simon — the hunt hit. '
             f'<b style="color:#fff;">{n} {html_mod.escape(disp)} listing'
             f'{"s" if n != 1 else ""}</b> surfaced. Move fast.</p>{market}{rows}'
             f'<p style="color:#46557a;font-size:11px;margin-top:18px;">'
             f'Blind spots (bot-blocked, check by hand): {", ".join(BLIND_SPOTS)}.</p>')
    subj = (f"{grail['emoji']} {disp.upper()} FOUND — {n} listing"
            f"{'s' if n != 1 else ''} ({finds[0]['source']}…)")
    txt_lines = [f"- [{('IN STOCK' if f['in_stock'] else 'SOLD OUT' if f['in_stock'] is False else 'LISTED')}] "
                 f"{f['source']}: {f['title']}{(' — $'+str(f['price'])) if f['price'] else ''}\n  {f['url']}"
                 for f in finds]
    txt = (f"{disp.upper()} — {grail['subtitle']} — FOUND\n"
           + (f"est. market: {grail['est_market']}\n" if grail.get('est_market') else '')
           + "\n" + "\n".join(txt_lines) +
           f"\n\nBlind spots (check by hand): {', '.join(BLIND_SPOTS)}\n"
           "instockornot.club bespoke grail hunt")
    return subj, _shell(inner, grail), txt


def _short_url(url):
    return re.sub(r'^https?://(www\.)?', '', url)


def build_armed_email():
    fleet = ''.join(f'<li style="margin:4px 0;color:#bccaeb">{html_mod.escape(s["name"])}'
                    f' <span style="color:#46557a">— {html_mod.escape(_short_url(s["url"]))}</span></li>'
                    for s in SOURCES)
    fleet += (f'<li style="margin:4px 0;color:#bccaeb">Reddit '
              f'<span style="color:#46557a">— {html_mod.escape("r/" + ", r/".join(REDDIT_SUBS))}</span></li>')
    if _ebay_active():
        fleet += ('<li style="margin:4px 0;color:#bccaeb">eBay '
                  '<span style="color:#46557a">— Browse API, newest first</span></li>')
    blind = list(BLIND_SPOTS)
    if not _ebay_active():
        blind.append('eBay (no API creds set — dormant)')
    roster = ' + '.join(g['display'] for g in GRAILS)
    inner = (f'<p style="color:#dfe6f2;font-size:14px;">The grail hunt is '
             f'<b style="color:#39d98a;">ARMED</b> for <b style="color:#fff;">'
             f'{html_mod.escape(roster)}</b>, running every 8 minutes.</p>'
             f'<div style="background:#0b101f;border:1px solid #1f2c4a;padding:16px;margin:16px 0;">'
             f'<div style="color:#7f93c4;font-size:10px;letter-spacing:0.2em;margin-bottom:8px;">'
             f'FLEET UNDER WATCH</div><ul style="margin:0;padding-left:18px">{fleet}</ul></div>'
             f'<p style="color:#dfe6f2;font-size:13px;">Deep-link dealers report the exact '
             f'item + live stock. The instant a Lunar Landing shows up <b style="color:#fff;">'
             f'in stock</b> you get a hit.</p>'
             f'<p style="color:#46557a;font-size:11px;margin-top:14px;">Known blind spots '
             f'(bot-blocked, not auto-scanned): {", ".join(blind)}.</p>')
    fleet_names = [s['name'] for s in SOURCES] + (['eBay'] if _ebay_active() else [])
    return "🗡 Grail hunt ARMED — " + " + ".join(g['display'] for g in GRAILS), _shell(inner), (
        f"Grail hunt ARMED ({' + '.join(g['display'] for g in GRAILS)}) — running every 8 min.\n\nFleet: "
        + ", ".join(fleet_names)
        + f"\nBlind spots (bot-blocked): {', '.join(blind)}\n")


def build_find_sms(finds, grail=None):
    """Short SMS body for a find. The email carries the full detail + links."""
    grail = grail or GRAILS[0]
    n = len(finds)
    f = finds[0]
    state = 'IN STOCK' if f['in_stock'] else ('listed' if f['in_stock'] is None else 'sold out')
    head = f"{grail['emoji']} {grail['display'].upper()} — {n} listing{'s' if n != 1 else ''} found!"
    lead = f"{f['source']} ({state})"
    return f"{head}\n{lead}\n{f['url']}\nDetails: {HUNTER_EMAIL}\nReply STOP to opt out."


def send_find_sms(finds, grail=None):
    if not HUNTER_PHONE:
        log.info("no DW_LUNAR_PHONE set — skipping SMS")
        return
    body = build_find_sms(finds, grail)
    if _send_twilio_sms(HUNTER_PHONE, body):
        log.info(f"SMS sent to {HUNTER_PHONE}")
    else:
        log.error(f"SMS failed to {HUNTER_PHONE}")


def _alertable(items):
    """Which fresh (find, seen_key) pairs are worth an alert: confirmed in-stock
    and LISTED/unknown (Reddit posts, text-scan pages — in_stock=None) both go
    out; only a confirmed SOLD OUT is dropped. Secondary market is where the
    SA-era grails actually surface, and those finds never carry dealer stock
    state ("more is better than less" — Simon 2026-07-03)."""
    return [(f, key) for f, key in items if f['in_stock'] is not False]


def run():
    log.info("Lunar hunt starting — HGR")
    all_finds = []
    for src in SOURCES:
        try:
            all_finds.extend(scan_source(src))
        except Exception as e:
            log.error(f"{src['name']} — scan error: {e}")
    try:
        all_finds.extend(scan_reddit())
    except Exception as e:
        log.error(f"Reddit — scan error: {e}")
    try:
        all_finds.extend(scan_ebay())
    except Exception as e:
        log.error(f"eBay — scan error: {e}")

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

    # One email (+SMS) per grail, each with its own branding.
    by_grail = {}
    for f, key in fresh:
        gkey = (f.get('grail') or GRAILS[0])['key']
        by_grail.setdefault(gkey, []).append((f, key))

    for gkey, items in by_grail.items():
        grail = next(g for g in GRAILS if g['key'] == gkey)
        items = _alertable(items)
        if not items:
            log.info(f"{grail['display']} — fresh find(s) but all confirmed sold out, skipping alert")
            continue
        finds_g = [f for f, _ in items]
        subj, html, txt = build_find_email(finds_g, grail)
        if send_email(subj, html, txt, to_addr=HUNTER_EMAIL):
            for _, key in items:
                db.mark_feed_seen(key)
            log.info(f"{grail['emoji']} ALERT SENT — {len(items)} fresh "
                     f"{grail['display']} find(s) to {HUNTER_EMAIL}")
            send_find_sms(finds_g, grail)   # text fires alongside email; never blocks it
        else:
            log.error(f"send_email failed for {gkey} — not marking seen, will retry next run")


def arm():
    subj, html, txt = build_armed_email()
    ok = send_email(subj, html, txt, to_addr=HUNTER_EMAIL)
    log.info(f"Armed notice sent: {ok}")
    if HUNTER_PHONE:
        body = (f"🗡 Grail hunt ARMED ({' + '.join(g['display'] for g in GRAILS)}) — watching dealers + Reddit every 8 min. "
                f"You'll get a text the instant one appears. Reply STOP to opt out.")
        log.info(f"Armed SMS sent: {_send_twilio_sms(HUNTER_PHONE, body)}")


if __name__ == '__main__':
    if '--arm' in sys.argv:
        arm()
    else:
        run()
