# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
page_kind.py — is this URL ONE product or a LIST of products? (two-path signup, 2026-10-22)

  product → the user wants "tell me when THIS is in stock"; no keyword needed, we take the
            title from the page and the availability flag decides.
  listing → the user is waiting for something to APPEAR; ask what.
  unknown → nothing structured on the page; treat like a listing (ask for a keyword).

Reuses the same structured extraction the alerter uses for deep links (JSON-LD Product,
then product-card DOM), so signup and polling agree on what a page is.
HGR
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agents'))
import product_extract  # noqa: E402


def detect(html, url):
    """Return {'kind': 'product'|'listing'|'unknown', 'product': {...}|None, 'count': int}."""
    products = []
    try:
        products = product_extract.from_structured_data(html or '', url) or []
    except Exception:
        products = []
    if not products:
        try:
            products = product_extract.from_product_cards(html or '', url) or []
        except Exception:
            products = []
    if len(products) == 1 and (products[0].get('title') or '').strip():
        p = products[0]
        return {'kind': 'product', 'count': 1,
                'product': {'title': p.get('title', '').strip(),
                            'available': bool(p.get('available')),
                            'price': str(p.get('price') or ''),
                            'url': p.get('url') or url}}
    if len(products) >= 2:
        return {'kind': 'listing', 'count': len(products), 'product': None}
    return {'kind': 'unknown', 'count': 0, 'product': None}
