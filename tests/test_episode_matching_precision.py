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

import os
import sys

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
