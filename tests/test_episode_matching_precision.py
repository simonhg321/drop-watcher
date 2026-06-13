#!/usr/bin/env python3
"""
test_episode_matching_precision.py — Corp #21 matching-precision fixes.

Audit (2026-06-13) against the real watch population (65 active URL-scoped, 62 with
empty maker, 16 availability-phrase keywords) ruled out Billboard's *universal*
maker-qualification and `drop['products']` binding for drop-watcher. The population-safe
subset built here:

  A. Same-item (notable_items-line) binding — a keyword/maker match must land inside a
     SINGLE product line, not span the flattened whole-catalog blob.
  B. CONDITIONAL maker-qualification — only when the watcher carries a maker; the 62
     maker-less watches keep firing on keyword alone.
  C. Matched-line stability / episode self-heal — a wrong/stale match decays instead of
     grinding to the 12-strike teardown.

Carve-outs preserved: availability-phrase keywords ('add to cart', 'in stock') and drops
with no notable_items fall back to current page-level behaviour (don't regress the 16
availability watches or sites that emit no per-product lines).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import per_user_alerter as pua


def _curated_drop(url, notable):
    """A curated (non-user) drop on `url` with per-product notable_items lines."""
    return {
        'url': url,
        'source': 'Curated Feed',
        'page_summary': '',
        'notable_items': notable,
        'page_excerpt': '',
        'keywords_found': [],
    }


# ── B + A: conditional maker-qual with same-line binding ─────────────────────
def test_url_scoped_maker_watch_requires_maker_and_keyword_in_same_line():
    """A URL-scoped watch that HAS a maker must not fire when the maker name and the
    keyword appear in DIFFERENT product lines (cross-product leakage). Mirrors the S60
    'Jack Wolf Cross Hatch' class of false positive, on the URL-scoped path."""
    w = {
        'id': 't1', 'email': 'x@y.z',
        'url': 'https://southernedges.com/collections/chris-reeve',
        'keywords': 'cross hatch',
        'maker': 'Chris Reeve',
    }
    drop = _curated_drop(
        'https://southernedges.com/collections/chris-reeve',
        ['Chris Reeve Sebenza 31 Magnacut', 'Jack Wolf Cross Hatch Handle'],
    )
    # maker in line 1, keyword in line 2 — no single line carries both.
    assert pua.matches_for_watcher_drop(w, drop) == []


def test_maker_watch_falls_back_to_page_level_when_no_notable_items():
    """Carve-out: a maker-carrying watch on a drop with NO per-product lines has nothing
    to bind to, so it must fall back to page-level matching and still fire — same-line
    binding must not silently kill maker watches on sites that emit no notable_items."""
    w = {
        'id': 't2', 'email': 'x@y.z',
        'url': 'https://maxaceknife.com/',
        'keywords': 'goliath',
        'maker': 'Maxace',
    }
    drop = {
        'url': 'https://maxaceknife.com/',
        'source': 'Curated Feed',
        'page_summary': 'Maxace Goliath MagnaCut now in stock',
        'notable_items': [],
        'page_excerpt': '',
        'keywords_found': [],
    }
    assert pua.matches_for_watcher_drop(w, drop) == ['goliath']


# ── C: matched-line stability / episode self-heal primitive ──────────────────
def test_matched_line_self_heals_when_specific_product_gone():
    """The product that triggered the episode is gone from a fresh scan; the keyword
    may still be present store-wide, but THIS line is not — the episode should be able
    to self-heal instead of grinding reminders to the 12-strike teardown."""
    matched = 'Chris Reeve Sebenza 31 Insingo - $650.00'
    fresh = ['Chris Reeve Inkosi Insingo - $475.00', 'Spyderco Para 3 - $180.00']
    assert pua.matched_line_in_stock(matched, fresh) is False


def test_matched_line_persists_despite_price_change():
    """A price change on the SAME product must NOT look like the item disappeared —
    identity is title-based, price-insensitive."""
    matched = 'Chris Reeve Sebenza 31 Insingo - $650.00'
    fresh = ['Chris Reeve Sebenza 31 Insingo - $675.00']
    assert pua.matched_line_in_stock(matched, fresh) is True


# ── Regression guards: population carve-outs the A+B change must preserve ─────
def test_makerless_url_watch_still_fires_on_keyword_alone():
    """62/65 of the live URL-scoped watches have NO maker. They must keep firing on a
    keyword anywhere on their page — conditional maker-qual must never gate them."""
    w = {
        'id': 't3', 'email': 'x@y.z',
        'url': 'https://www.knifejoy.com/',
        'keywords': 'sebenza',
        'maker': '',
    }
    drop = _curated_drop(
        'https://www.knifejoy.com/',
        ['Chris Reeve Large Sebenza 31 Magnacut - $650.00', 'Spyderco Para 3 - $180.00'],
    )
    assert 'sebenza' in pua.matches_for_watcher_drop(w, drop)


def test_maker_watch_fires_when_maker_and_keyword_share_a_line():
    """The positive case: maker and keyword in the SAME product line must still fire."""
    w = {
        'id': 't4', 'email': 'x@y.z',
        'url': 'https://www.knifejoy.com/',
        'keywords': 'inkosi',
        'maker': 'Chris Reeve',
    }
    drop = _curated_drop(
        'https://www.knifejoy.com/',
        ['Chris Reeve Inkosi Insingo Magnacut - $475.00', 'Spyderco Para 3 - $180.00'],
    )
    assert pua.matches_for_watcher_drop(w, drop) == ['inkosi']


# ── C wiring helpers: capture matched line at open, self-heal at re-scan ──────
def test_lines_for_matches_captures_the_triggering_product_line():
    """At episode-open we store the specific notable_items line(s) that carried a
    matched keyword — so self-heal can later check THAT product, not the keyword."""
    notable = ['Benchmade Bugout - $140.00', 'Chris Reeve Small Sebenza 31 - $475.00']
    assert pua.lines_for_matches(notable, ['sebenza']) == [
        'Chris Reeve Small Sebenza 31 - $475.00'
    ]


def test_matched_lines_in_text_true_when_product_still_listed():
    """instock_text is the space-joined in-stock lines; the stored product line is
    still present (despite a price change) → episode stays open."""
    stored = ['Chris Reeve Small Sebenza 31 - $475.00']
    fresh_blob = 'benchmade bugout - $140.00 chris reeve small sebenza 31 - $499.00'
    assert pua.matched_lines_in_text(stored, fresh_blob) is True


def test_matched_lines_in_text_false_when_specific_product_gone():
    """The keyword 'sebenza' could still be store-wide, but the SPECIFIC product that
    opened the episode is gone from the fresh in-stock text → self-heal can close."""
    stored = ['Chris Reeve Small Sebenza 31 Insingo - $475.00']
    fresh_blob = 'chris reeve large sebenza 31 tanzanite - $1200.00 spyderco para 3'
    assert pua.matched_lines_in_text(stored, fresh_blob) is False


# ── C wired end-to-end through episode_sweep ─────────────────────────────────
def test_episode_self_heals_through_sweep_when_product_gone(tmp_path):
    """End-to-end: an open episode whose stored product line is gone from the fresh
    scan self-heals (closes) — even though the keyword 'sebenza' is still in stock
    store-wide. This is the exact #21 teardown bug; the old keyword-on-blob closure
    would keep it open and grind reminders to the 12-strike teardown."""
    dbm = pua.db
    dbm.DB_PATH = str(tmp_path / 'ep.db')
    dbm._initialized_paths.discard(dbm.DB_PATH)

    now = datetime.now(timezone.utc)
    url = 'https://knifejoy.com/'
    opened = (now - timedelta(hours=2)).isoformat()
    dbm.open_episode(
        'k1', 'w1', 'knifejoy.com', url, 'sebenza', 'e@x.z', opened,
        matched_lines=json.dumps(['Chris Reeve Small Sebenza 31 - $475.00']),
    )
    # Fresh scan: the watched product is GONE, but a DIFFERENT Sebenza is in stock —
    # keyword 'sebenza' still present store-wide.
    dbm.record_page_scan(
        url, 'knifejoy.com',
        'Chris Reeve Large Sebenza 31 Tanzanite - $1200.00',
        (now - timedelta(hours=1)).isoformat(),
    )

    pua.episode_sweep(now)

    assert dbm.get_open_episode('k1') is None  # self-healed → closed
