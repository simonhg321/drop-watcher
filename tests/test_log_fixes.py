#!/usr/bin/env python3
"""
test_log_fixes.py — two load fixes from the 2026-10-22 log review (Simon: "go fix plz"):
  1. collection_fetch remembers hosts whose /products.json is not Shopify and stops
     probing them every cycle (was ~half our traffic to non-Shopify dealers).
  2. web_watcher counts 404/410 on a user URL toward consecutive_not_found; after
     GONE_THRESHOLD in a row the watch is retired and the user emailed "page is gone".
Run: python3 -m pytest tests/test_log_fixes.py -v
"""
import importlib
import os
import sys
import time
from unittest.mock import patch

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

import collection_fetch as cf  # noqa: E402


# ── 1. not-Shopify host memory ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_not_shopify():
    cf._not_shopify.clear()
    yield
    cf._not_shopify.clear()


def _recording_fetch(reply):
    calls = []
    def fetch_page(url, ssl_permissive=False):
        calls.append(url)
        return reply(url)
    fetch_page.calls = calls
    return fetch_page


def test_404_products_json_marks_host_and_skips_next_probe():
    fp = _recording_fetch(lambda u: None)                       # products.json 404 → None
    cf.fetch_shopify_collection('https://www.dlttrading.com/x', fp, max_pages=1)
    cf.fetch_shopify_collection('https://www.dlttrading.com/y', fp, max_pages=1)
    probes = [c for c in fp.calls if 'products.json' in c]
    assert len(probes) == 1, fp.calls
    assert 'dlttrading.com' in cf._not_shopify


def test_html_at_products_json_marks_host_too():
    fp = _recording_fetch(lambda u: '<html>not json</html>')
    cf.fetch_shopify_collection('https://smkw.com/a', fp, max_pages=1)
    cf.fetch_shopify_collection('https://smkw.com/b', fp, max_pages=1)
    assert len([c for c in fp.calls if 'products.json' in c]) == 1


def test_not_shopify_mark_expires():
    fp = _recording_fetch(lambda u: None)
    cf.fetch_shopify_collection('https://monkeyedge.com/a', fp, max_pages=1)
    cf._not_shopify['monkeyedge.com'] = time.time() - cf.NOT_SHOPIFY_TTL - 1
    cf.fetch_shopify_collection('https://monkeyedge.com/b', fp, max_pages=1)
    assert len([c for c in fp.calls if 'products.json' in c]) == 2


def test_real_shopify_host_is_not_marked():
    fp = _recording_fetch(lambda u: '{"products":[{"id":1,"title":"T","handle":"t","vendor":"V","tags":[],"variants":[{"price":"1","available":true}],"images":[]}]}')
    cf.fetch_shopify_collection('https://nullknives.com/', fp, max_pages=1)
    assert 'nullknives.com' not in cf._not_shopify


# ── 2. dead user pages retire ────────────────────────────────────────────────

@pytest.fixture
def ww(tmp_path, monkeypatch):
    for k, sub in [('DW_CONFIG_DIR', 'config'), ('DW_DATA_DIR', 'data'), ('DW_LOG_DIR', 'logs'), ('DW_WWW_DIR', 'www')]:
        monkeypatch.setenv(k, str(tmp_path / sub)); (tmp_path / sub).mkdir()
    monkeypatch.setenv('DW_DB', str(tmp_path / 'data' / 'test.db'))
    import paths, db
    importlib.reload(paths); importlib.reload(db)
    import web_watcher
    web_watcher.last_http_status.clear()
    yield web_watcher, db
    monkeypatch.undo()
    importlib.reload(paths); importlib.reload(db)


URL = 'https://smkw.com/spyderco-para-military-2-gone/'


def _seed(db, url=URL, email='d@h.com'):
    db.add_watcher({'id': 'w404', 'verify_token': None, 'unsubscribe_token': 'u1', 'url': url,
                    'keywords': 'pm2', 'keywords_raw': 'pm2', 'maker': '', 'email': email, 'name': '',
                    'priority': 'high', 'phone': '', 'sms_approved': False, 'sms_verify_code': None,
                    'sms_verify_expires': None, 'active': True, 'created': '2026-05-01T00:00:00+00:00',
                    'last_alert': None, 'alert_count': 0, 'mode': 'listing'})


class _Resp:
    def __init__(self, code): self.status_code = code; self.headers = {}; self.is_redirect = False; self.content = b''
    def close(self): pass
    def raise_for_status(self):
        if self.status_code >= 400:
            e = requests.HTTPError(f'{self.status_code} Client Error'); e.response = self; raise e


def test_fetch_page_records_404_status(ww):
    web_watcher, _ = ww
    with patch('requests.Session.get', return_value=_Resp(404)):
        assert web_watcher.fetch_page(URL) is None
    assert web_watcher.last_http_status[URL] == 404


def test_fetch_page_records_200_status(ww):
    web_watcher, _ = ww
    with patch('requests.Session.get', return_value=_Resp(200)):
        web_watcher.fetch_page(URL)
    assert web_watcher.last_http_status[URL] == 200


def test_404_counts_toward_not_found_and_retires_at_threshold(ww):
    web_watcher, db = ww
    _seed(db)
    web_watcher.last_http_status[URL] = 404
    sent = []
    with patch.object(web_watcher, 'send_page_gone_email', side_effect=lambda w: sent.append(w['email']) or True):
        for i in range(web_watcher.GONE_THRESHOLD - 1):
            assert web_watcher.note_user_fetch_failure(URL) == []
        assert db.get_watcher_by_id('w404')['consecutive_not_found'] == web_watcher.GONE_THRESHOLD - 1
        assert db.get_watcher_by_id('w404')['active'] == 1
        retired = web_watcher.note_user_fetch_failure(URL)
    assert [w['id'] for w in retired] == ['w404']
    assert db.get_watcher_by_id('w404')['active'] == 0
    assert sent == ['d@h.com']


def test_transient_failure_does_not_count(ww):
    web_watcher, db = ww
    _seed(db)
    web_watcher.last_http_status[URL] = None       # timeout / connection error
    assert web_watcher.note_user_fetch_failure(URL) == []
    assert db.get_watcher_by_id('w404')['consecutive_not_found'] == 0


def test_success_resets_counter(ww):
    web_watcher, db = ww
    _seed(db)
    web_watcher.last_http_status[URL] = 404
    web_watcher.note_user_fetch_failure(URL)
    web_watcher.note_user_fetch_ok(URL)
    assert db.get_watcher_by_id('w404')['consecutive_not_found'] == 0


def test_user_loop_wires_failure_and_ok_hooks():
    src = open(os.path.join(ROOT, 'agents', 'web_watcher.py')).read()
    loop = src[src.index('for uurl, usite in user_sites.items():'):]
    assert 'note_user_fetch_failure(uurl)' in loop
    assert 'note_user_fetch_ok(uurl)' in loop
