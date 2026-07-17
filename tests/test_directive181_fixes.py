#!/usr/bin/env python3
"""
test_directive181_fixes.py — Corp directive 181 (qwen3-coder review via Typhoon,
2026-07-17): item dedup key collision, page_cache eviction, config fail-safe.
Run: python3 -m pytest tests/test_directive181_fixes.py -v
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))


# ── finding 2: item dedup key must hash the FULL item text ───────────────────

def test_item_key_distinguishes_long_items_with_same_prefix():
    from web_watcher import item_key
    prefix = ('Chris Reeve Knives Large Sebenza 31 Unique Graphics Glass Blasted '
              'CGG Left Handed Ladder Damascus ')
    assert len(prefix) >= 80
    a = item_key('src', prefix + 'Box and Papers — $625')
    b = item_key('src', prefix + 'Drop Point Micarta — $580')
    assert a != b


def test_item_key_stable_for_same_item():
    from web_watcher import item_key
    assert item_key('src', 'Umnumzaan Drop') == item_key('src', 'Umnumzaan Drop')


# ── finding 1: page_cache / stale-count eviction ─────────────────────────────

def test_prune_stale_cache_drops_dead_keys():
    from web_watcher import prune_stale_cache
    cache = {'a': 1, 'b': 2, 'gone': 3}
    prune_stale_cache(cache, {'a', 'b'})
    assert cache == {'a': 1, 'b': 2}


# ── finding 4: broken sources.yaml must not silently disable suppression ─────

def test_no_user_alert_domains_failsafe_on_parse_error(tmp_path):
    import per_user_alerter as pua
    bad = tmp_path / 'sources.yaml'
    bad.write_text('websites: [unclosed\n  - {{{')
    domains = pua.load_no_user_alert_domains(path=str(bad))
    assert 'chrisreeve.com' in domains        # failsafe, not empty set


def test_no_user_alert_domains_failsafe_on_missing_file(tmp_path):
    import per_user_alerter as pua
    domains = pua.load_no_user_alert_domains(path=str(tmp_path / 'nope.yaml'))
    assert 'chrisreeve.com' in domains
