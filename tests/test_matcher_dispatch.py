"""Tests for DW_MATCHER dispatch in per_user_alerter.

Default (DW_MATCHER unset or 'blob') must produce zero behavior change — this is
the critical safety property for prod. The fts5 branch must call record_match.query
and return the same shape as the blob path: a list of matched keyword strings.
"""
import os
import importlib


def test_default_is_blob(monkeypatch):
    monkeypatch.delenv('DW_MATCHER', raising=False)
    import per_user_alerter
    importlib.reload(per_user_alerter)
    assert per_user_alerter._matcher_mode() == 'blob'


def test_fts5_mode_dispatches_to_record_match(monkeypatch):
    monkeypatch.setenv('DW_MATCHER', 'fts5')
    import per_user_alerter
    importlib.reload(per_user_alerter)
    called = {}
    monkeypatch.setattr(per_user_alerter, 'record_match',
                        type('M', (), {'query': staticmethod(
                            lambda w, source_url=None: called.setdefault('hit', True) or [])}))
    watcher = {"url": "https://shop.com/collections/all", "keywords": "smf", "maker": "Strider"}
    drop = {"url": "https://shop.com/collections/all", "notable_items": [], "instock_text": ""}
    per_user_alerter.matches_for_watcher_drop(watcher, drop)
    assert called.get('hit') is True
