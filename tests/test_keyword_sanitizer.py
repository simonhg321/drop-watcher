#!/usr/bin/env python3
"""
test_keyword_sanitizer.py — silent keyword correction at signup/backfill
(Simon 2026-07-17). Every deterministic case here is a real prod failure.
Run: python3 -m pytest tests/test_keyword_sanitizer.py -v
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from keyword_sanitizer import sanitize


# ── normalization ────────────────────────────────────────────────────────────

def test_clean_input_unchanged():
    r = sanitize('Sebenza 25', maker='Chris Reeve Knives')
    assert r['keywords'] == 'Sebenza 25'
    assert r['maker'] == 'Chris Reeve Knives'
    assert r['changed'] is False


def test_whitespace_and_newlines_collapsed():
    r = sanitize('Inkosi Insingo Glass Blasted Large Black Canvas Unique Graphic\nDesign')
    assert '\n' not in r['keywords']
    assert '  ' not in r['keywords']


def test_dedupe_case_insensitive():
    r = sanitize('CGG, cgg, Unique Graphic')
    assert r['keywords'] == 'CGG, Unique Graphic'
    assert r['changed'] is True


def test_empty_items_dropped():
    r = sanitize('sebenza, , ,inkosi')
    assert r['keywords'] == 'sebenza, inkosi'


# ── junk keyword classes (real prod watches) ─────────────────────────────────

def test_single_char_keyword_dropped():
    # salimnice: 'PP, H, Classic' — 'H' substring-matched constantly
    r = sanitize('PP, H, Classic')
    assert r['keywords'] == 'PP, Classic'
    assert 'H' in r['dropped']


def test_storefront_terms_dropped_when_others_remain():
    r = sanitize('sebenza, in stock')
    assert r['keywords'] == 'sebenza'
    assert 'in stock' in r['dropped']


def test_all_storefront_keeps_original():
    # dkargarzadeh 'In stock', turbo91199 'discount, sale, clearance':
    # never empty a watch — keep original, flag for the AI pass
    r = sanitize('discount, sale, clearance')
    assert r['keywords'] == 'discount, sale, clearance'
    assert r['changed'] is False
    assert r['notes'] == 'all_dropped'


def test_add_to_cart_buy_it_now_all_dropped():
    r = sanitize('add to cart, buy it now')
    assert r['notes'] == 'all_dropped'
    assert r['keywords'] == 'add to cart, buy it now'


# ── maker split (the SMF STRIDER case) ───────────────────────────────────────

def test_maker_phrase_split_and_maker_filled():
    # Simon's b007fa3c: 'SMF STRIDER' matched 0 of 329 strider drops in 14d
    r = sanitize('SMF STRIDER')
    assert r['keywords'] == 'SMF, STRIDER'
    assert r['maker'] == 'Strider Knives'
    assert r['changed'] is True


def test_maker_split_never_overwrites_user_maker():
    r = sanitize('SMF STRIDER', maker='Mick Strider Custom Knives')
    assert r['keywords'] == 'SMF, STRIDER'
    assert r['maker'] == 'Mick Strider Custom Knives'


def test_unresolvable_token_blocks_split():
    # '25' doesn't resolve — a real model phrase must survive intact
    r = sanitize('Sebenza 25')
    assert r['keywords'] == 'Sebenza 25'


def test_mixed_phrase_not_split():
    r = sanitize('Lunar Landing CGG')
    assert r['keywords'] == 'Lunar Landing CGG'


def test_single_word_maker_keyword_left_alone():
    r = sanitize('strider')
    assert r['keywords'] == 'strider'
    assert r['maker'] == ''


def test_tokens_resolving_to_different_makers_not_split():
    # 'sebenza' -> Chris Reeve, 'smf' -> Strider: disagreement = no split
    r = sanitize('sebenza smf')
    assert r['keywords'] == 'sebenza smf'


# ── safety rails ─────────────────────────────────────────────────────────────

def test_empty_input_survives():
    r = sanitize('')
    assert r['keywords'] == ''
    assert r['changed'] is False


def test_never_raises_on_garbage(monkeypatch):
    import keyword_sanitizer
    monkeypatch.setattr(keyword_sanitizer.maker_resolve, 'resolve',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('yaml gone')))
    r = sanitize('SMF STRIDER')
    assert r['keywords'] == 'SMF STRIDER'   # resolver down -> no split, no crash


# ── AI-suggestion validation (pure, no anthropic) ────────────────────────────

def test_ai_correction_applied_when_valid():
    from keyword_sanitizer import apply_ai_correction
    det = {'keywords': 'discount, sale, clearance', 'notes': 'all_dropped'}
    assert apply_ai_correction(det, ['Strider SMF', 'SnG']) == 'Strider SMF, SnG'


def test_ai_correction_rejected_when_junk():
    from keyword_sanitizer import apply_ai_correction
    det = {'keywords': 'discount, sale, clearance', 'notes': 'all_dropped'}
    assert apply_ai_correction(det, ['in stock']) is None      # still storefront
    assert apply_ai_correction(det, []) is None                # empty
    assert apply_ai_correction(det, ['x']) is None             # single char
    assert apply_ai_correction(det, ['a' * 80]) is None        # absurd length
    assert apply_ai_correction(det, ['k%d' % i for i in range(9)]) is None  # >8 items


# ── signup route integration ─────────────────────────────────────────────────

import importlib
import uuid as _uuid
from unittest.mock import patch


@pytest.fixture
def signup_client(tmp_path, monkeypatch):
    monkeypatch.setenv('DW_CODE_DIR', str(tmp_path))
    monkeypatch.setenv('DW_CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setenv('DW_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('DW_LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setenv('DW_WWW_DIR', str(tmp_path / 'www'))
    monkeypatch.setenv('DW_ENV_FILE', str(tmp_path / '.env'))
    monkeypatch.setenv('DW_DB', str(tmp_path / 'data' / 'test.db'))
    for d in ['config', 'data', 'logs', 'www']:
        (tmp_path / d).mkdir()
    import shutil
    shutil.copy(os.path.join(ROOT, 'config', 'makers.yaml'),
                tmp_path / 'config' / 'makers.yaml')   # maker split needs the real index
    import paths; importlib.reload(paths)
    import db; importlib.reload(db)
    if 'watcher_signup' in sys.modules:
        del sys.modules['watcher_signup']
    import watcher_signup
    importlib.reload(watcher_signup)
    watcher_signup.app.config['TESTING'] = True
    with watcher_signup.app.test_client() as c:
        yield db, watcher_signup, c


def test_signup_sanitizes_and_preserves_raw(signup_client):
    db, ws, c = signup_client
    with patch.object(ws, 'send_verification_email', return_value=True), \
         patch.object(ws, 'correct_keywords_ai', return_value=None):
        r = c.post('/api/watch', json={
            'email': 'x@example.com', 'url': '', 'keywords': 'SMF STRIDER',
            'maker': 'Strider Knives'})
    assert r.status_code in (200, 201), r.get_json()
    w = db.get_watchers_by_email('x@example.com')[0]
    assert w['keywords'] == 'SMF, STRIDER'
    assert w['keywords_raw'] == 'SMF STRIDER'


def test_signup_ai_rescues_junk_keywords(signup_client):
    db, ws, c = signup_client
    with patch.object(ws, 'send_verification_email', return_value=True), \
         patch.object(ws, 'correct_keywords_ai', return_value=['Strider SMF']):
        r = c.post('/api/watch', json={
            'email': 'y@example.com', 'url': '', 'keywords': 'discount, clearance',
            'maker': 'Strider Knives'})
    assert r.status_code in (200, 201), r.get_json()
    w = db.get_watchers_by_email('y@example.com')[0]
    assert w['keywords'] == 'Strider SMF'
    assert w['keywords_raw'] == 'discount, clearance'


# ── backfill tool ────────────────────────────────────────────────────────────

def _load_backfill():
    spec = importlib.util.spec_from_file_location(
        'backfill_keywords', os.path.join(ROOT, 'bin', 'backfill_keywords.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def backfill_env(tmp_path, monkeypatch):
    monkeypatch.setenv('DW_CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setenv('DW_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('DW_DB', str(tmp_path / 'data' / 'test.db'))
    for d in ['config', 'data']:
        (tmp_path / d).mkdir()
    import shutil
    shutil.copy(os.path.join(ROOT, 'config', 'makers.yaml'),
                tmp_path / 'config' / 'makers.yaml')
    import paths; importlib.reload(paths)
    import db; importlib.reload(db)
    import uuid
    def mk(kw, maker=''):
        wid = uuid.uuid4().hex[:8]
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO watchers (id, email, url, keywords, maker, unsubscribe_token,"
                " created, active) VALUES (?,?,?,?,?,?,?,1)",
                (wid, 'u@example.com', '', kw, maker, 'tok', '2026-07-17T00:00:00+00:00'))
        return wid
    return db, mk


def test_backfill_dry_run_changes_nothing(backfill_env):
    db, mk = backfill_env
    wid = mk('SMF STRIDER')
    bf = _load_backfill()
    changes = bf.backfill(apply=False, use_ai=False)
    assert any(c['id'] == wid and c['keywords'] == 'SMF, STRIDER' for c in changes)
    assert db.get_watcher_by_id(wid)['keywords'] == 'SMF STRIDER'   # untouched


def test_backfill_apply_writes_and_preserves_raw(backfill_env):
    db, mk = backfill_env
    wid = mk('PP, H, Classic')
    clean = mk('Sebenza 25', maker='Chris Reeve Knives')
    bf = _load_backfill()
    bf.backfill(apply=True, use_ai=False)
    w = db.get_watcher_by_id(wid)
    assert w['keywords'] == 'PP, Classic'
    assert w['keywords_raw'] == 'PP, H, Classic'
    assert db.get_watcher_by_id(clean)['keywords'] == 'Sebenza 25'
    assert not (db.get_watcher_by_id(clean)['keywords_raw'] or '')  # untouched watch: no raw stamp
