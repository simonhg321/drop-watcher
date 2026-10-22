#!/usr/bin/env python3
"""
test_simple_mode.py — Simon 2026-10-22: "Keyword + URL = instockornot = text or email."
  * settings polling.curated_sources: false  → web_watcher polls NO curated dealers
  * user-URL fetches are strict: exactly the URL given (plus one products.json read on
    Shopify), never a pagination walk.
Run: python3 -m pytest tests/test_simple_mode.py -v
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

import collection_fetch as cf

SOURCES = {'websites': [
    {'name': 'A', 'url': 'https://a.example', 'enabled': True},
    {'name': 'B', 'url': 'https://b.example', 'enabled': False},
]}


def test_curated_roster_off_by_setting():
    import web_watcher
    assert web_watcher.active_websites(SOURCES, {'polling': {'curated_sources': False}}) == []


def test_curated_roster_on_by_default():
    import web_watcher
    assert [s['name'] for s in web_watcher.active_websites(SOURCES, {'polling': {}})] == ['A']


CARD_PAGE = """<html><body>
<div class="product-card"><a href="/products/sebenza-31">Sebenza 31</a><span class="price">$450</span></div>
<link rel="next" href="/collections/all?page=2">
</body></html>"""


def _recording_fetch(pages):
    calls = []
    def fetch_page(url, ssl_permissive=False):
        calls.append(url)
        return pages.get(url)
    return fetch_page, calls


def test_strict_non_shopify_is_one_request():
    url = 'https://shop.example/collections/all'
    fetch_page, calls = _recording_fetch({url: CARD_PAGE,
                                          url + '?page=2': CARD_PAGE,
                                          url + '?page=3': CARD_PAGE})
    text, products, cands = cf.fetch_collection(url, fetch_page, strict=True)
    assert text and 'Sebenza' in text
    # one optional products.json probe (it's a /collections/ URL) + the page itself,
    # and never a ?page=N walk
    assert url in calls and len(calls) <= 2
    assert not any('page=2' in c for c in calls)


def test_default_mode_still_paginates():
    url = 'https://shop.example/collections/all'
    fetch_page, calls = _recording_fetch({url: CARD_PAGE,
                                          url + '?page=2': CARD_PAGE,
                                          url + '?page=3': CARD_PAGE})
    cf.fetch_collection(url, fetch_page)
    assert len(calls) > 1


def test_strict_shopify_reads_one_products_page():
    url = 'https://knives.myshopify.example/collections/crk'
    full = {'products': [{'id': i, 'title': f'Knife {i}', 'handle': f'k{i}', 'vendor': 'CRK',
                          'tags': [], 'variants': [{'available': True, 'price': '1'}]}
                         for i in range(cf.SHOPIFY_LIMIT)]}
    def fetch_page(u, ssl_permissive=False):
        calls.append(u)
        return json.dumps(full) if 'products.json' in u else None
    calls = []
    text, products, _ = cf.fetch_collection(url, fetch_page, strict=True)
    assert products and len(products) == cf.SHOPIFY_LIMIT
    assert [c for c in calls if 'products.json' in c] == [c for c in calls if 'page=1' in c]
    assert len(calls) == 1


def test_user_loop_calls_fetch_strict():
    src = open(os.path.join(ROOT, 'agents', 'web_watcher.py')).read()
    user_loop = src[src.index('User-submitted URL watches'):]
    assert 'uurl, fetch_page, log=log, hints=None, strict=True' in user_loop
