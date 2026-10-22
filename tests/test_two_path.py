#!/usr/bin/env python3
"""
test_two_path.py — two-path signup (Simon 2026-10-22):
  product page  → "tell me when THIS is in stock" (no keyword; availability flag decides)
  listing page  → "what are you waiting to see on this page?" (keyword as before)
Run: python3 -m pytest tests/test_two_path.py -v
"""
import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

PRODUCT_URL = 'https://www.dlt-example.com/chris-reeve-large-inkosi-crosshatch-610'
TITLE = 'Chris Reeve Large Inkosi - Drop Point - Crosshatch - Glass Bead Blasted'


def product_html(available=False, title=TITLE):
    ld = {"@context": "https://schema.org", "@type": "Product", "name": title,
          "brand": {"@type": "Brand", "name": "Chris Reeve Knives"},
          "offers": {"@type": "Offer", "price": "625", "priceCurrency": "USD",
                     "availability": "https://schema.org/" + ("InStock" if available else "OutOfStock"),
                     "url": PRODUCT_URL}}
    body = ('<h1>%s</h1><p>%s</p>' % (title, ('Add to cart. ' if available else 'Sold out. ') * 40))
    return '<html><head><script type="application/ld+json">%s</script></head><body>%s</body></html>' % (json.dumps(ld), body)


def listing_html():
    items = [{"@type": "Product", "name": "Sebenza 31 %d" % i, "url": "https://www.dlt-example.com/s%d" % i,
              "offers": {"@type": "Offer", "availability": "https://schema.org/InStock", "price": "450"}} for i in range(4)]
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": it} for i, it in enumerate(items)]}
    return '<html><head><script type="application/ld+json">%s</script></head><body>%s</body></html>' % (
        json.dumps(ld), 'Chris Reeve collection. ' * 40)


# ── page_kind.detect ─────────────────────────────────────────────────────────

def test_detect_single_product_out_of_stock():
    import page_kind
    r = page_kind.detect(product_html(False), PRODUCT_URL)
    assert r['kind'] == 'product'
    assert r['product']['title'] == TITLE
    assert r['product']['available'] is False
    assert r['product']['price'] == '625'


def test_detect_single_product_in_stock():
    import page_kind
    r = page_kind.detect(product_html(True), PRODUCT_URL)
    assert r['kind'] == 'product' and r['product']['available'] is True


def test_detect_listing():
    import page_kind
    r = page_kind.detect(listing_html(), 'https://www.dlt-example.com/chris-reeve-knives')
    assert r['kind'] == 'listing' and r['product'] is None
    assert r['count'] == 4


def test_detect_unknown_plain_page():
    import page_kind
    r = page_kind.detect('<html><body>' + 'nothing structured here. ' * 50 + '</body></html>', 'https://x.example/p')
    assert r['kind'] == 'unknown' and r['product'] is None


# ── Flask endpoints ──────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    for k, sub in [('DW_CONFIG_DIR', 'config'), ('DW_DATA_DIR', 'data'), ('DW_LOG_DIR', 'logs'), ('DW_WWW_DIR', 'www')]:
        monkeypatch.setenv(k, str(tmp_path / sub)); (tmp_path / sub).mkdir()
    monkeypatch.setenv('DW_CODE_DIR', str(tmp_path))
    monkeypatch.setenv('DW_ENV_FILE', str(tmp_path / '.env'))
    monkeypatch.setenv('DW_DB', str(tmp_path / 'data' / 'test.db'))
    monkeypatch.setenv('RESEND_API_KEY', 'test-key')
    import paths, db
    importlib.reload(paths); importlib.reload(db)
    sys.modules.pop('watcher_signup', None)
    import watcher_signup as ws
    ws.app.config['TESTING'] = True
    with ws.app.test_client() as c:
        yield c, ws
    monkeypatch.undo()
    importlib.reload(paths); importlib.reload(db)


class FakeResp:
    status_code = 200
    def __init__(self, text): self.text = text


def test_check_url_reports_product_page(client):
    c, ws = client
    import safe_fetch
    with patch.object(safe_fetch, 'safe_get', return_value=FakeResp(product_html(False))):
        j = c.post('/api/check-url', json={'url': PRODUCT_URL}).get_json()
    assert j['ok'] is True
    assert j['kind'] == 'product'
    assert j['product']['title'] == TITLE and j['product']['available'] is False
    assert 'sold out' in j['msg'].lower() or 'in stock' in j['msg'].lower()


def test_check_url_reports_listing_page(client):
    c, ws = client
    import safe_fetch
    with patch.object(safe_fetch, 'safe_get', return_value=FakeResp(listing_html())):
        j = c.post('/api/check-url', json={'url': 'https://www.dlt-example.com/chris-reeve-knives'}).get_json()
    assert j['ok'] is True and j['kind'] == 'listing'


@patch('watcher_signup.send_verification_email', return_value=True)
@patch('watcher_signup.send_confirmation_email', return_value=True)
def test_product_watch_needs_no_keywords(_c, _e, client):
    c, ws = client
    ws._fetch_page_html = lambda u: product_html(False)
    ws._fetch_page_text = lambda u: 'chris reeve knives'
    with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
         patch.object(ws, 'classify_dealer', return_value={'is_dealer': True, 'confidence': 0.9, 'category': 'knife dealer'}):
        r = c.post('/api/watch', json={'url': PRODUCT_URL, 'mode': 'product', 'email': 'p@h.com'})
    assert r.status_code == 201, r.get_json()
    import db
    w = db.get_watchers_by_email('p@h.com')[0]
    assert w['mode'] == 'product'
    assert w['keywords'] == TITLE          # we fill it in; the user never typed a keyword
    assert r.get_json().get('product', {}).get('title') == TITLE


@patch('watcher_signup.send_verification_email', return_value=True)
@patch('watcher_signup.send_confirmation_email', return_value=True)
def test_product_watch_skips_maker_prompt(_c, _e, client):
    c, ws = client
    ws._fetch_page_html = lambda u: product_html(False)
    ws._fetch_page_text = lambda u: 'chris reeve knives'
    with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
         patch.object(ws, 'classify_dealer', return_value={'is_dealer': True, 'confidence': 0.9, 'category': 'knife dealer'}):
        r = c.post('/api/watch', json={'url': PRODUCT_URL, 'mode': 'product', 'email': 'p2@h.com'})
    assert r.status_code == 201 and not r.get_json().get('confirm')


def test_product_watch_on_non_product_page_asks_for_keyword(client):
    c, ws = client
    ws._fetch_page_html = lambda u: '<html><body>' + 'plain text page ' * 60 + '</body></html>'
    ws._fetch_page_text = lambda u: 'knives'
    with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
         patch.object(ws, 'classify_dealer', return_value={'is_dealer': True, 'confidence': 0.9, 'category': 'knife dealer'}):
        r = c.post('/api/watch', json={'url': 'https://www.dlt-example.com/some-page', 'mode': 'product', 'email': 'p3@h.com'})
    assert r.status_code == 400
    assert 'keyword' in r.get_json()['error'].lower() or 'what' in r.get_json()['error'].lower()


@patch('watcher_signup.send_verification_email', return_value=True)
@patch('watcher_signup.send_confirmation_email', return_value=True)
def test_listing_watch_still_requires_keywords(_c, _e, client):
    c, ws = client
    r = c.post('/api/watch', json={'url': 'https://www.dlt-example.com/chris-reeve-knives', 'mode': 'listing', 'email': 'l@h.com'})
    assert r.status_code == 400 and 'keywords' in r.get_json()['error'].lower()


# ── matching: product-mode watch matches its own page's in-stock drop ────────

def _watcher(mode, url=PRODUCT_URL, kw=TITLE):
    return {'id': 'w1', 'email': 'p@h.com', 'url': url, 'keywords': kw, 'maker': '', 'mode': mode}


def _drop(available=True, url=PRODUCT_URL):
    return {'source': 'dlt-example.com (user)', 'url': url, 'event': 'user_watch_alert',
            'notable_items': [TITLE] if available else [], 'page_excerpt': TITLE + ' add to cart',
            'products': [{'title': TITLE, 'url': url, 'available': available, 'price': '625'}]}


@pytest.mark.parametrize('matcher', ['blob', 'fts5'])
def test_product_watch_matches_in_stock_drop_in_both_matchers(matcher, monkeypatch, tmp_path):
    monkeypatch.setenv('DW_DB', str(tmp_path / 't.db'))
    import db; importlib.reload(db)
    import per_user_alerter as pua; importlib.reload(pua)
    monkeypatch.setattr(pua, '_matcher_mode', lambda: matcher)
    assert pua.matches_for_watcher_drop(_watcher('product'), _drop(True)) == [TITLE]
    assert pua.matches_for_watcher_drop(_watcher('product'), _drop(False)) == []
    # a different product page on the same domain must not fire it
    assert pua.matches_for_watcher_drop(_watcher('product'), _drop(True, url='https://www.dlt-example.com/other-knife-7')) == []


# ── web_watcher: product-mode decision comes from the availability flag, no AI ─

def test_product_stock_result_in_stock():
    import web_watcher
    r = web_watcher.product_stock_result([{'title': TITLE, 'url': PRODUCT_URL, 'available': True, 'price': '625'}])
    assert r['alert_worthy'] is True
    assert r['notable_items'] == [TITLE]
    assert r['priority'] == 'high'
    assert r['in_stock'] == {TITLE: 1}


def test_product_stock_result_sold_out():
    import web_watcher
    r = web_watcher.product_stock_result([{'title': TITLE, 'url': PRODUCT_URL, 'available': False}])
    assert r['alert_worthy'] is False


def test_product_stock_result_not_a_product_page():
    import web_watcher
    assert web_watcher.product_stock_result(None) is None
    assert web_watcher.product_stock_result([{'title': 'a', 'available': True}, {'title': 'b', 'available': True}]) is None


def test_user_sites_carry_mode():
    import web_watcher
    rows = [{'url': PRODUCT_URL, 'keywords': TITLE, 'id': 'a', 'mode': 'product'},
            {'url': 'https://x.example/c', 'keywords': 'sebenza', 'id': 'b', 'mode': 'listing'},
            {'url': 'https://x.example/c', 'keywords': 'inkosi', 'id': 'c'}]
    sites = web_watcher.user_watch_sites(rows)
    modes = {s['url']: s.get('mode', 'listing') for s in sites}
    assert modes[PRODUCT_URL] == 'product' and modes['https://x.example/c'] == 'listing'


def test_user_loop_uses_product_stock_result_before_ai():
    src = open(os.path.join(ROOT, 'agents', 'web_watcher.py')).read()
    loop = src[src.index('User-submitted URL watches'):]
    assert loop.index('product_stock_result(') < loop.index('analyze_user_page(')


# ── maker prompt retired (Simon 2026-10-22 "fix em") ─────────────────────────

@patch('watcher_signup.send_verification_email', return_value=True)
@patch('watcher_signup.send_confirmation_email', return_value=True)
def test_listing_watch_without_maker_is_created_not_prompted(_c, _e, client):
    """The new page never shows a maker prompt, so the server must not emit one:
    a maker-less listing keyword with no maker_confirmed flag creates the watch."""
    c, ws = client
    ws._fetch_page_html = lambda u: listing_html()
    ws._fetch_page_text = lambda u: 'chris reeve knives sebenza inkosi'
    with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
         patch.object(ws, 'classify_dealer', return_value={'is_dealer': True, 'confidence': 0.9, 'category': 'knife dealer'}):
        r = c.post('/api/watch', json={'url': 'https://www.dlt-example.com/chris-reeve-knives',
                                       'mode': 'listing', 'keywords': 'crosshatch', 'email': 'nm@h.com'})
    assert r.status_code == 201, r.get_json()
    assert not r.get_json().get('confirm')


@patch('watcher_signup.send_verification_email', return_value=True)
@patch('watcher_signup.send_confirmation_email', return_value=True)
def test_listing_keyword_naming_a_maker_still_adopts_it(_c, _e, client):
    """Silent maker adoption stays: a keyword that names a maker sets watcher.maker."""
    c, ws = client
    import shutil, db, paths, maker_resolve
    shutil.copy(os.path.join(ROOT, 'config', 'makers.yaml'), os.path.join(paths.CONFIG_DIR, 'makers.yaml'))
    maker_resolve._indexes.cache_clear()
    ws._fetch_page_html = lambda u: listing_html()
    ws._fetch_page_text = lambda u: 'chris reeve knives sebenza inkosi'
    with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
         patch.object(ws, 'classify_dealer', return_value={'is_dealer': True, 'confidence': 0.9, 'category': 'knife dealer'}):
        r = c.post('/api/watch', json={'url': 'https://www.dlt-example.com/chris-reeve-knives',
                                       'mode': 'listing', 'keywords': 'chris reeve, inkosi', 'email': 'ma@h.com'})
    maker_resolve._indexes.cache_clear()
    assert r.status_code == 201, r.get_json()
    w = db.find_watcher_by_email_url('ma@h.com', 'https://www.dlt-example.com/chris-reeve-knives')
    assert w is not None and w['maker'] == 'Chris Reeve Knives'
