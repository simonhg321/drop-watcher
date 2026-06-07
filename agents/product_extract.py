# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
product_extract.py — turn raw HTML into structured product records so alerts can
deep-link the matched item without fuzzy name→anchor guessing.

Two extractors, both returning the canonical product shape used everywhere downstream
(collection_fetch._parse_products / per_user_alerter.select_matched_products):

    {"title": str, "vendor": str, "url": str,
     "available": bool, "tags": list[str], "price": str}

  • from_structured_data(html, base_url)        — JSON-LD / microdata Product schema
  • from_product_cards(html, base_url, hints)   — repeated product-card DOM blocks

Both return [] (never raise, never fabricate) when nothing confident is found, so the
resolution chain falls through to the next tier.
"""
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _product_record(title, url, available, price='', vendor='', tags=None):
    return {
        'title': (title or '').strip(),
        'vendor': (vendor or '').strip(),
        'url': url or '',
        'available': bool(available),
        'tags': tags or [],
        'price': str(price or '').strip(),
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
            available = any(_availability_in_stock((o or {}).get('availability')) for o in offer_list)
            out.append(_product_record(
                title=pr.get('name'),
                url=urljoin(base_url or '', url) if url else '',
                available=available,
                price=first_offer.get('price', ''),
                vendor=(pr.get('brand') or {}).get('name') if isinstance(pr.get('brand'), dict) else pr.get('brand') or '',
            ))
    return [p for p in out if p['title']]


def _price_from(text):
    m = _PRICE_RE.search(text or '')
    return m.group(1).replace(',', '') if m else ''


_BLOCK_TAGS = frozenset({'div', 'li', 'article', 'section', 'tr', 'td', 'figure'})


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
        if not href or not title:
            continue
        out.append(_product_record(
            title=title, url=urljoin(base_url or '', href),
            available=not _SOLD_OUT_RE.search(block_text), price=price))
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

    out, seen = [], set()
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        href_l = href.lower()
        if not any(p in href_l for p in _PRODUCT_HREF):
            continue
        if any(b in href_l for b in _BAD_HREF):
            continue
        abs_href = urljoin(base_url or '', href)
        if abs_href in seen:
            continue
        title = a.get_text(' ', strip=True)
        if len(title) < 4:
            continue
        seen.add(abs_href)
        block_text = _card_container(a).get_text(' ', strip=True)
        out.append(_product_record(
            title=title, url=abs_href,
            available=not _SOLD_OUT_RE.search(block_text),
            price=_price_from(block_text)))
    return out
