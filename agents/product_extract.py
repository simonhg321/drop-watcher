# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
product_extract.py — turn raw HTML into structured product records so alerts can
deep-link the matched item without fuzzy name→anchor guessing.

Two extractors, both returning the canonical product shape used everywhere downstream
(collection_fetch._parse_products / per_user_alerter.select_matched_products):

    {"title": str, "vendor": str, "url": str,
     "available": bool, "tags": list[str], "price": str, "confidence": str}

  • from_structured_data(html, base_url)        — JSON-LD / microdata Product schema
  • from_product_cards(html, base_url, hints)   — repeated product-card DOM blocks

Both return [] (never raise, never fabricate) when nothing confident is found, so the
resolution chain falls through to the next tier.
"""
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from linkpick import same_site, title_from_slug


def _same_site_url(abs_url, base_url):
    """True if abs_url is http(s) and same-site as base_url. Cross-site or non-http
    product URLs must never be emitted into an alert (open-redirect/phishing guard)."""
    if not abs_url.startswith(('http://', 'https://')):
        return False
    base_host = urlparse(base_url or '').hostname
    return bool(base_host) and same_site(urlparse(abs_url).hostname, base_host)


def _product_record(title, url, available, price='', vendor='', tags=None, confidence='high'):
    return {
        'title': (title or '').strip(),
        'vendor': (vendor or '').strip(),
        'url': url or '',
        'available': bool(available),
        'tags': tags or [],
        'price': str(price or '').strip(),
        'confidence': confidence,
    }


def _availability_in_stock(value):
    """schema.org availability → bool. InStock / available → True; everything else False."""
    v = str(value or '').lower()
    return ('instock' in v) or v.endswith('available')


def _iter_jsonld_products(obj):
    """Yield every dict whose @type is (or includes) 'Product' anywhere in a JSON-LD blob."""
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld_products(x)
        return
    if not isinstance(obj, dict):
        return
    t = obj.get('@type')
    types = t if isinstance(t, list) else [t]
    if any(str(x).lower() == 'product' for x in types):
        yield obj
    for v in obj.values():
        if isinstance(v, (list, dict)):
            yield from _iter_jsonld_products(v)


_PRICE_RE = re.compile(r'\$\s*([\d,]+(?:\.\d{2})?)')
_PRODUCT_HREF = ('/products/', '/product/', '/p/', '/dp/')
_BAD_HREF = ('/cart', '/search', '/account', '/login', '/policies', '/pages/')
_URL_LIKE_RE = re.compile(r'^https?://', re.I)
_HAS_ALPHA_RE = re.compile(r'[a-zA-Z]{2}')
_SOLD_OUT_RE = re.compile(r'sold[\s-]?out|out[\s-]?of[\s-]?stock|notify me|unavailable', re.I)


def from_structured_data(html, base_url):
    """Products from JSON-LD (and microdata) Product schema. [] if none present."""
    if not html:
        return []
    out = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return []
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or tag.get_text() or '')
        except Exception:
            continue
        for pr in _iter_jsonld_products(data):
            raw_offers = pr.get('offers') or {}
            offer_list = raw_offers if isinstance(raw_offers, list) else [raw_offers]
            first_offer = (offer_list[0] or {}) if offer_list else {}
            url = pr.get('url') or first_offer.get('url') or ''
            abs_url = urljoin(base_url or '', url) if url else ''
            if abs_url and not _same_site_url(abs_url, base_url):
                continue
            available = any(_availability_in_stock((o or {}).get('availability')) for o in offer_list)
            out.append(_product_record(
                title=pr.get('name'),
                url=abs_url,
                available=available,
                price=first_offer.get('price', ''),
                vendor=(pr.get('brand') or {}).get('name') if isinstance(pr.get('brand'), dict) else pr.get('brand') or '',
            ))
    return [p for p in out if p['title']]


def _is_usable_title(text):
    """True if text looks like a real human product name (not a URL, not empty junk)."""
    if not text:
        return False
    t = text.strip()
    if _URL_LIKE_RE.match(t):
        return False
    if '/images/' in t:
        return False
    if not _HAS_ALPHA_RE.search(t):
        return False
    return True


def _anchor_title(a):
    """Anchor's product title: prefer the anchor's title attribute (reliable on many
    dealer sites), then visible text, aria-label, inner img alt.
    Image-only anchors whose text is a URL return '' so the caller can fall back to
    slug derivation."""
    # title attribute is reliable (set server-side, never an image URL)
    attr_title = (a.get('title') or '').strip()
    if _is_usable_title(attr_title):
        return attr_title
    # visible text — reject if it looks like a URL
    text = a.get_text(' ', strip=True)
    if text and _is_usable_title(text):
        return text
    # aria-label
    aria = (a.get('aria-label') or '').strip()
    if _is_usable_title(aria):
        return aria
    # img alt
    img = a.find('img')
    if img:
        alt = (img.get('alt') or '').strip()
        if _is_usable_title(alt):
            return alt
    return ''


def _price_from(text):
    # Returns the FIRST non-zero $ amount in the text. Skips $0.00 / $0 placeholders
    # (e.g. Lamnia's struck-through "original" price field) which are worse than empty.
    for m in _PRICE_RE.finditer(text or ''):
        val = m.group(1).replace(',', '')
        try:
            if float(val) == 0.0:
                continue
        except ValueError:
            pass
        return val
    return ''


_BLOCK_TAGS = frozenset({'div', 'li', 'article', 'section', 'tr', 'td', 'figure'})
_STRIP_SEP_RE = re.compile(r'^[\s\-–—|:·]+|[\s\-–—|:·]+$')
_COLLAPSE_WS_RE = re.compile(r'\s{2,}')


def _normalize_title(t):
    t = _COLLAPSE_WS_RE.sub(' ', t or '').strip()
    return _STRIP_SEP_RE.sub('', t).strip()


def _card_container(anchor):
    """Climb to the nearest block-level ancestor that plausibly holds one product card."""
    node = anchor.parent
    for _ in range(4):
        if node is None:
            return anchor
        if getattr(node, 'name', None) in _BLOCK_TAGS:
            return node
        node = node.parent
    return anchor.parent or anchor


def _from_hints(soup, base_url, hints):
    out = []
    for card in soup.select(hints.get('card', '')):
        link_el = card.select_one(hints['link']) if hints.get('link') else card.find('a', href=True)
        href = (link_el.get('href') if link_el else '') or ''
        title_el = card.select_one(hints['title']) if hints.get('title') else None
        title = (title_el.get_text(' ', strip=True) if title_el else (link_el.get_text(' ', strip=True) if link_el else ''))
        price_el = card.select_one(hints['price']) if hints.get('price') else None
        price = _price_from(price_el.get_text(' ', strip=True) if price_el else card.get_text(' ', strip=True))
        block_text = card.get_text(' ', strip=True)
        if not href or any(b in href.lower() for b in _BAD_HREF):
            continue
        abs_href = urljoin(base_url or '', href)
        if not _same_site_url(abs_href, base_url):
            continue
        if not title:
            continue
        out.append(_product_record(
            title=title, url=abs_href,
            available=not _SOLD_OUT_RE.search(block_text), price=price,
            confidence='high'))
    return out


def from_product_cards(html, base_url, hints=None):
    """Structured products from repeated product-card DOM blocks. [] if none confident."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return []
    if hints and hints.get('card'):
        try:
            return [p for p in _from_hints(soup, base_url, hints) if p['title']]
        except Exception:
            return []

    # keyed by abs_href so we can upgrade a bad title when a better anchor appears
    best: dict = {}
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        href_l = href.lower()
        if not any(p in href_l for p in _PRODUCT_HREF):
            continue
        if any(b in href_l for b in _BAD_HREF):
            continue
        abs_href = urljoin(base_url or '', href)
        if not _same_site_url(abs_href, base_url):
            continue
        title = _anchor_title(a)
        # Prefer the anchor's own text for price/availability (per-card scope).
        # For single-anchor cards (Lamnia) the anchor wraps everything, so own_text
        # already contains that card's price. For multi-element cards where price is a
        # sibling span, own_text has no price → fall back to the climbed container so
        # sibling prices are still captured.
        own_text = a.get_text(' ', strip=True)
        own_price = _price_from(own_text)
        scope_text = own_text if own_price else _card_container(a).get_text(' ', strip=True)
        if abs_href in best:
            # Upgrade title if existing record has a URL/junk title and this one is better
            existing = best[abs_href]
            if not _is_usable_title(existing['title']) and _is_usable_title(title) and len(title) >= 4:
                existing['title'] = _normalize_title(title)
            elif _is_usable_title(title) and len(title) > len(existing['title']):
                existing['title'] = _normalize_title(title)
            continue
        # Slug fallback when no usable title found from the anchor
        if not _is_usable_title(title) or len(title) < 4:
            title = title_from_slug(abs_href)
        if not title or len(title) < 4:
            continue
        # Normalize scraped title: collapse internal whitespace, strip separator punctuation.
        title = _normalize_title(title)
        if not title or len(title) < 4:
            continue
        best[abs_href] = _product_record(
            title=title, url=abs_href,
            available=not _SOLD_OUT_RE.search(scope_text),
            price=own_price or _price_from(scope_text),
            confidence='low')
    return list(best.values())
