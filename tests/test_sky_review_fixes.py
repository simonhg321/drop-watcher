#!/usr/bin/env python3
"""
test_sky_review_fixes.py — regression tests for Sky's S57 code review (Corp task #19).
Covers the P1 fixes: explicit-JSON-null hardening, link-tier same-site enforcement,
honest /collections/all fallback, best_anchor confidence floor, consent-safe verify,
maker-scoped global-watch dedup.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from test_core import tmp_env  # noqa: F401  (fixture reuse)


# ── P1 #1: alert emails survive explicit JSON nulls ─────────────────────────

class TestAlerterNullHardening:
    def _null_alert(self):
        return {
            'priority': None,
            'source': None,
            'url': None,
            'timestamp': None,
            'notable_items': None,
            'matches': None,
            'page_summary': None,
            'drop_announcement': {
                'detected': True, 'maker': None, 'description': None,
                'timing': None, 'confidence': None,
            },
        }

    def test_immediate_email_with_all_nulls(self):
        import alerter
        subject, html, text = alerter.format_immediate_email(self._null_alert())
        assert 'DROP WATCHER' in subject

    def test_digest_row_with_null_timestamp(self):
        import alerter
        out = alerter.format_digest_email([self._null_alert()])
        assert out  # no TypeError from None[:16]


# ── P1 #2/#3: link tiers — same-site only, honest last resort ───────────────

class TestResolveDropItemLinks:
    BASE = 'https://shop.example.com/collections/knives'

    def _drop(self, detail, candidates=None):
        return {
            'url': self.BASE,
            'products': [],
            'notable_items': [],
            'notable_items_detail': detail,
            'link_candidates': candidates or [],
        }

    def test_protocol_relative_url_is_dropped(self):
        import per_user_alerter as pua
        items = pua.resolve_drop_items(
            self._drop([{'name': 'CRK Sebenza 31', 'url': '//evil.example.org/x', 'price': ''}]),
            ['sebenza'])
        assert all('evil.example.org' not in (i.get('url') or '') for i in items)

    def test_cross_site_absolute_url_is_dropped(self):
        import per_user_alerter as pua
        items = pua.resolve_drop_items(
            self._drop([{'name': 'CRK Sebenza 31', 'url': 'https://other.example.net/p/x', 'price': ''}]),
            ['sebenza'])
        assert all('other.example.net' not in (i.get('url') or '') for i in items)

    def test_bare_relative_url_is_absolutised(self):
        import per_user_alerter as pua
        items = pua.resolve_drop_items(
            self._drop([{'name': 'CRK Sebenza 31', 'url': 'products/sebenza-31', 'price': ''}]),
            ['sebenza'])
        assert items and items[0]['url'].startswith('https://shop.example.com/')

    def test_last_resort_skipped_for_non_shopify_drop(self):
        import per_user_alerter as pua
        drop = {'url': 'https://www.reddit.com/r/Knife_Swap/comments/abc/',
                'products': [], 'notable_items': [], 'notable_items_detail': [],
                'link_candidates': []}
        assert pua.resolve_drop_items(drop, ['sebenza']) == []

    def test_last_resort_builds_on_origin_for_shopify_drop(self):
        import per_user_alerter as pua
        drop = {'url': 'https://shop.example.com/collections/knives?cat=knives',
                'products': [], 'notable_items': [], 'notable_items_detail': [],
                'link_candidates': [{'text': 'Unrelated Thing',
                                     'href': 'https://shop.example.com/products/unrelated'}]}
        items = pua.resolve_drop_items(drop, ['sebenza'])
        assert items and items[0]['url'] == 'https://shop.example.com/collections/all'


# ── P1 #4: best_anchor confidence floor ──────────────────────────────────────

class TestBestAnchorFloor:
    def test_weak_match_returns_none(self):
        from bs4 import BeautifulSoup
        import linkpick
        html = ('<a href="/products/half-face-blades-g6">Half Face Blades</a>'
                '<a href="/collections/all">All</a>')
        soup = BeautifulSoup(html, 'html.parser')
        # 2-ish shared tokens — the #6289 mislink class — must fall back, not link
        assert linkpick.best_anchor(soup, 'Lile DOT Fixed Blade Knife') is None

    def test_strong_match_still_resolves(self):
        from bs4 import BeautifulSoup
        import linkpick
        html = '<a href="/products/lile-dot-fixed-blade-knife">Lile DOT Fixed Blade Knife</a>'
        soup = BeautifulSoup(html, 'html.parser')
        assert linkpick.best_anchor(soup, 'Lile DOT Fixed Blade Knife') is not None


# ── P1 #5/#6: consent-safe verify + maker-scoped global dedup ────────────────

class TestWatcherDbFixes:
    def _watcher(self, wid, **kw):
        from datetime import datetime, timezone
        base = {'id': wid, 'email': 'u@example.com', 'url': '', 'keywords': 'sebenza',
                'maker': '', 'name': '', 'priority': 'high',
                'unsubscribe_token': 'tok-' + wid, 'verify_token': None, 'active': False,
                'created': datetime.now(timezone.utc).isoformat()}
        base.update(kw)
        return base

    def test_global_watch_dedup_is_maker_scoped(self, tmp_env):
        import db
        db.add_watcher(self._watcher('g1', maker='Chris Reeve', active=True))
        db.add_watcher(self._watcher('g2', maker='Grimsmo', active=True))
        found = db.find_watcher_by_email_url('u@example.com', '', maker='Grimsmo')
        assert found and found['id'] == 'g2'
        found = db.find_watcher_by_email_url('u@example.com', '', maker='Chris Reeve')
        assert found and found['id'] == 'g1'

    def test_verify_does_not_resurrect_unsubscribed(self, tmp_env):
        import db
        # unsubscribed: inactive, no pending verify token
        db.add_watcher(self._watcher('w-unsub', active=False, verify_token=None))
        # pending: inactive, awaiting verification
        db.add_watcher(self._watcher('w-pend', maker='Grimsmo',
                                     active=False, verify_token='vt-1'))
        db.activate_pending_watchers('u@example.com')
        assert not db.get_watcher_by_id('w-unsub')['active']
        pend = db.get_watcher_by_id('w-pend')
        assert pend['active'] and not pend['verify_token']
