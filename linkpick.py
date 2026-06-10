#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
# All rights reserved. See LICENSE for terms.

"""
linkpick.py — shared product deep-link logic for The Billboard.

Two jobs, one scorer:
  • CLICK time (/api/go, /api/find): given a page's soup and a matched keyword,
    pick the single best product anchor.  → best_anchor() / find_in_html()
  • SCRAPE time (web_watcher): the keyword isn't known yet, so capture ALL
    product-looking anchors onto the drop. Later, best_from_candidates() resolves
    one of them for whatever keyword ends up matching.  → extract_candidates()

The scoring (score_anchor) is shared so a stored candidate resolves the same way
a live anchor would: keyword in the link TEXT, keyword/tokens in the href SLUG,
product-URL shape — penalising cart/search/policy destinations.
"""

import re
from urllib.parse import urljoin, urlparse

# Product pages look like these; the BAD list is destinations a buyer never wants
# (cart/search/policy pages that often carry the keyword in nav or breadcrumbs).
PRODUCT_PATH_HINTS = ('/product', '/products/', '/p/', '/item', '/shop/',
                      '/buy', '/dp/', '/collections/', '/listing')
BAD_PATH_HINTS = ('/cart', '/search', '/login', '/account', '/wishlist',
                  '/compare', '/faq', '/help', '/contact', '/about', '/blog',
                  '/policy', '/policies', '/terms', '/privacy', '/shipping',
                  '/returns', '/gift', '/register', '/signup', '/sitemap')

# Tunables shared with the search widget.
FIND_SNIPPET_RADIUS = 90       # chars around each match
FIND_MAX_MATCHES_PER_URL = 6
LINK_INDEX_MAX = 40            # max product anchors stored per drop (bounds raw_json)

# A candidate must clear this score to be trusted as a deep-link. Generic-word overlap
# ("fixed blade") scores low; a real match (name in text, slug in href) scores high.
# Below the floor → return None so the alert falls back to the page link, never a wrong
# product. Tuned so the #6289 mislinks fail closed while real matches pass.
# Empirically: Half-Face for "Lile DOT Fixed Blade Knife" (2 shared tokens + product path)
# scores 14; G6-180 for its correct needle scores 15; so 15 is the clean separation point.
MIN_CANDIDATE_SCORE = 15


def same_site(host_a, host_b):
    """True if two hostnames are the same site (ignoring www / sub-domain)."""
    a = (host_a or '').lower()
    b = (host_b or '').lower()
    a = a[4:] if a.startswith('www.') else a
    b = b[4:] if b.startswith('www.') else b
    if not a or not b:
        return False
    return a == b or a.endswith('.' + b) or b.endswith('.' + a)


def _usable_href(href):
    h = (href or '').strip().lower()
    return bool(h) and h != '#' and not h.startswith(('javascript:', 'mailto:', 'tel:'))


def _has_deep_path(url):
    """A slug-like path segment (long or hyphenated) — catches product pages on
    sites that don't use a /product/ prefix, e.g. dlttrading.com/chris-reeve-large-sebenza-31."""
    path = urlparse(url).path.strip('/')
    return any(len(seg) >= 6 or '-' in seg for seg in path.split('/') if seg)


def score_anchor(text, href, needle):
    """Score how well an anchor matches `needle`. 0 = not relevant (never chosen).

    Relevance gate first (otherwise a bare 'Products' nav link would win on the
    product-pattern bonus alone), then signals: keyword in text (+8), keyword slug
    in href (+6), per-token href/text hits, product-URL shape (+4), bad-path (-8).
    """
    needle_l = (needle or '').lower().strip()
    href_l = (href or '').lower()
    if not needle_l or not _usable_href(href_l):
        return 0
    atxt = (text or '').lower()
    slug = re.sub(r'[^a-z0-9]+', '-', needle_l).strip('-')
    tokens = [t for t in re.split(r'[^a-z0-9]+', needle_l) if len(t) > 2]
    text_full = needle_l in atxt
    href_slug = bool(slug) and slug in href_l
    href_toks = sum(1 for t in tokens if t in href_l)
    text_toks = sum(1 for t in tokens if t in atxt)
    relevant = text_full or href_slug or href_toks >= 1 or (tokens and text_toks >= len(tokens))
    if not relevant:
        return 0
    score = 0
    if text_full:
        score += 8
    if href_slug:
        score += 6
    score += href_toks * 3
    score += text_toks * 2
    if any(p in href_l for p in PRODUCT_PATH_HINTS):
        score += 4
    if any(b in href_l for b in BAD_PATH_HINTS):
        score -= 8
    return score


def best_anchor(soup, needle):
    """Best deep-link anchor on a live page for `needle`. Raw href or None.

    Caller (/api/go) absolutises + same-site-guards the result itself.
    Same MIN_CANDIDATE_SCORE floor as best_candidate — a weak match must
    fall back, not deep-link a wrong product (#6289 class).
    """
    best, best_score = None, MIN_CANDIDATE_SCORE - 1
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        if not _usable_href(href):
            continue
        s = score_anchor(a.get_text(' ', strip=True), href, needle)
        if s > best_score:
            best_score, best = s, href
    return best


def best_candidate(candidates, needle):
    """Resolve the best stored candidate for `needle` as {'text','href'}, or None.

    Returns None unless the best score clears MIN_CANDIDATE_SCORE — a weak (generic-word)
    match must fall back to the page link, not deep-link to a wrong product.
    candidates: list of {'text','href'} dicts (or (text, href) tuples).
    """
    best, best_score = None, MIN_CANDIDATE_SCORE - 1
    for c in (candidates or []):
        if isinstance(c, dict):
            text, href = c.get('text', ''), c.get('href', '')
        else:
            text, href = (c[0], c[1]) if len(c) >= 2 else ('', '')
        if not href:
            continue
        s = score_anchor(text, href, needle)
        if s > best_score:
            best_score, best = s, {'text': text, 'href': href}
    return best


def best_from_candidates(candidates, needle):
    """Best stored candidate's absolute href for `needle`, or None."""
    c = best_candidate(candidates, needle)
    return c['href'] if c else None


# Availability words dealers/AI prefix onto an item label ("IN STOCK — Sebenza 31").
# Stripped so the product NAME resolves the link, not the status word.
_STATUS_PREFIX = re.compile(
    r'^\s*(in[\s-]?stock|notify me|out of stock|sold out|available|'
    r'pre[\s-]?order|back[\s-]?order|coming soon|low stock)\b\s*[—\-:|]*\s*',
    re.I)


def strip_status_prefix(text):
    """Strip a leading availability/status word + separator from an item label."""
    return _STATUS_PREFIX.sub('', text or '').strip()


def _term_overlap(name, terms):
    """Count of shared word tokens between an item name and the matched terms."""
    ntoks = {t for t in re.split(r'[^a-z0-9]+', (name or '').lower()) if t}
    ttoks = {t for t in re.split(r'[^a-z0-9]+', ' '.join(terms).lower()) if t}
    return len(ntoks & ttoks)


def resolve_alert_candidate(candidates, notable_items=None, keywords=None, makers=None):
    """Best deep-link candidate {'text','href'} for an alert, or None.

    Resolve against the SPECIFIC matched product (a notable_item) before the raw
    keyword: a watch keyword can be generic/aspirational ("White 360 camera") and
    its tokens ("360") can score a *different* product on the page (G6 Pro 360)
    higher than the one actually in stock (G6-180). The product name the email
    shows is the trustworthy needle.

    Order tried (first that resolves wins): matched notable_items (most term
    overlap first) → keyword(s) → maker(s) → any leftover notable_item.
    """
    candidates = candidates or []
    keywords = keywords or []
    makers = makers or []
    terms = keywords + makers
    notables = [n for n in (strip_status_prefix(x) for x in (notable_items or [])) if len(n) >= 4]
    matched = sorted((n for n in notables if _term_overlap(n, terms) > 0),
                     key=lambda n: _term_overlap(n, terms), reverse=True)
    leftover = [n for n in notables if _term_overlap(n, terms) == 0]
    for needle in [*matched, *keywords, *makers, *leftover]:
        c = best_candidate(candidates, needle)
        if c:
            return c
    return None


def resolve_alert_link(candidates, notable_items=None, keywords=None, makers=None):
    """resolve_alert_candidate(), returning just the absolute href (or None)."""
    c = resolve_alert_candidate(candidates, notable_items, keywords, makers)
    return c['href'] if c else None


# Link text that's a call-to-action, not a product name — unusable as a label.
_GENERIC_LINK_TEXT = {
    'buy now', 'shop now', 'view', 'view product', 'view details', 'add to cart',
    'details', 'more', 'shop', 'buy', 'learn more', 'quick view', 'see more',
    'read more', 'select options', 'add to bag', 'view all', 'sold out',
}


def clean_title(text, limit=70):
    """Tidy an anchor's text into a display product name, or '' if it's a generic
    CTA / too short to be useful (caller then falls back to title_from_slug, then
    the dealer name)."""
    t = ' '.join((text or '').split())
    if len(t) < 4 or t.lower() in _GENERIC_LINK_TEXT:
        return ''
    return t[:limit]


def title_from_slug(url, limit=70):
    """Derive a readable product name from a URL's last path segment, for when the
    anchor text is empty/generic. e.g. /products/chris-reeve-inyoni-drop-point-magnacut
    → "Chris Reeve Inyoni Drop Point Magnacut". '' if the slug isn't word-like
    (bare numeric id, etc.)."""
    from urllib.parse import urlparse, unquote
    path = urlparse(url or '').path.rstrip('/')
    seg = unquote(path.split('/')[-1]) if path else ''
    seg = re.sub(r'\.(html?|php|aspx?)$', '', seg, flags=re.I)  # strip extensions
    words = [w for w in re.split(r'[-_]+', seg) if w and not w.isdigit()]
    title = ' '.join(words)
    if len(title) < 3:
        return ''
    # Title-case words; UPPERCASE alphanumeric model codes (126710blro → 126710BLRO)
    # and leave existing acronyms (CRK) alone.
    def cap(w):
        if any(c.isdigit() for c in w) and any(c.isalpha() for c in w):
            return w.upper()
        return w if w.isupper() else w.capitalize()
    return ' '.join(cap(w) for w in words)[:limit]


# Slug words that mark a link as navigation/category/account rather than an
# individual product — deprioritised so the cap keeps real products.
_NAV_SLUG_WORDS = ('reward', 'landing', 'coming-soon', 'newest', 'arrival',
                   'restock', 'gift-card', 'shop-all', 'clearance', 'on-sale',
                   'brands', 'makers', 'best-sell', 'featured', 'new-products',
                   'all-products', 'view-all')
_STRICT_PRODUCT_HINTS = ('/products/', '/product/', '/p/', '/dp/', '/item', '/listing')


def _cand_priority(href, text):
    """Needle-independent guess at how product-like a link is, used to rank
    candidates before the cap. Individual products (rich slug, product pattern)
    beat category/nav links."""
    h = href.lower()
    score = 0
    if any(p in h for p in _STRICT_PRODUCT_HINTS):
        score += 5
    elif '/collections/' in h or '/shop/' in h:
        score += 1  # category page — a useful landing, but weaker than a product
    last = urlparse(h).path.strip('/').split('/')[-1] if urlparse(h).path.strip('/') else ''
    score += min(last.count('-'), 4)  # multi-word slugs read as real products
    if len(text) >= 8:
        score += 1
    if any(w in h for w in _NAV_SLUG_WORDS):
        score -= 5
    return score


def extract_candidates(soup, base_url, limit=LINK_INDEX_MAX):
    """Capture product-looking anchors from a page for later resolution.

    No needle here — at scrape time we don't yet know which user keyword will
    match. Absolutises against base_url, same-site only, drops cart/search/policy
    links, keeps anchors that look like products (product-URL pattern OR a
    slug-like deep path with real text), dedups by href, RANKS by product-likeness
    and keeps the top `limit` (so a long page's nav links don't crowd out the real
    products). Returns list of {'text','href'}.
    """
    base_host = urlparse(base_url).hostname if base_url else None
    seen, cands = set(), []
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        if not _usable_href(href):
            continue
        text = a.get_text(' ', strip=True)
        if not text:
            text = (a.get('aria-label') or a.get('title') or '').strip()
            if not text:
                img = a.find('img')
                if img:
                    text = (img.get('alt') or '').strip()
        abs_href = urljoin(base_url or '', href)
        if not abs_href.startswith(('http://', 'https://')):
            continue
        if base_host and not same_site(urlparse(abs_href).hostname, base_host):
            continue
        href_l = abs_href.lower()
        if any(b in href_l for b in BAD_PATH_HINTS):
            continue
        productish = any(p in href_l for p in PRODUCT_PATH_HINTS) or (len(text) >= 4 and _has_deep_path(abs_href))
        if not productish:
            continue
        if abs_href in seen:
            continue
        seen.add(abs_href)
        cands.append({'text': text[:160], 'href': abs_href, '_p': _cand_priority(abs_href, text)})
    cands.sort(key=lambda c: c['_p'], reverse=True)
    return [{'text': c['text'], 'href': c['href']} for c in cands[:limit]]


def find_in_html(html_text, needle):
    """Up to FIND_MAX_MATCHES_PER_URL (snippet, link) tuples from a page.

    Every hit carries the same `link` — the best product anchor for `needle`.
    Snippets stay per-occurrence so the search widget can show context.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    best_link = best_anchor(soup, needle)
    text = soup.get_text(' ', strip=True)
    needle_l = needle.lower()
    text_l = text.lower()

    hits = []
    pos = 0
    while len(hits) < FIND_MAX_MATCHES_PER_URL:
        idx = text_l.find(needle_l, pos)
        if idx < 0:
            break
        start = max(0, idx - FIND_SNIPPET_RADIUS)
        end = min(len(text), idx + len(needle) + FIND_SNIPPET_RADIUS)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = '…' + snippet
        if end < len(text):
            snippet = snippet + '…'
        hits.append({'snippet': snippet, 'link': best_link})
        pos = idx + len(needle)
    return hits
