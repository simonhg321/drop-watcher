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


def from_product_cards(html, base_url, hints=None):
    """Products from repeated product-card DOM blocks. [] if none found. (Task 3)"""
    raise NotImplementedError("from_product_cards is Task 3 — not yet implemented")
