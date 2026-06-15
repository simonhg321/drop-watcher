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


def _fts5(monkeypatch, tmp_path):
    monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('DW_MATCHER', 'fts5')
    import paths; importlib.reload(paths)
    import db; importlib.reload(db)
    import per_user_alerter as pua; importlib.reload(pua)
    return pua, db


def test_fts5_suppresses_monitor_only_domain(monkeypatch, tmp_path):
    pua, db = _fts5(monkeypatch, tmp_path)
    monkeypatch.setattr(pua, 'NO_USER_ALERT_DOMAINS', {'chrisreeve.com'})
    watcher = {'url': 'https://chrisreeve.com/collections/all', 'keywords': 'sebenza',
               'maker': 'Chris Reeve'}
    drop = {'url': 'https://chrisreeve.com/collections/all', 'source': 'curated',
            'products': [{'title': 'Large Sebenza 31', 'vendor': 'Chris Reeve', 'available': True}]}
    # Index a matching record under the drop URL so an UNGUARDED fts5 path WOULD leak.
    import record_index; importlib.reload(record_index)
    record_index.index_scan(drop['url'].lower(), drop['products'])
    assert pua.matches_for_watcher_drop(watcher, drop) == []


def test_fts5_user_drop_only_matches_exact_url(monkeypatch, tmp_path):
    pua, db = _fts5(monkeypatch, tmp_path)
    monkeypatch.setattr(pua, 'NO_USER_ALERT_DOMAINS', set())
    watcher = {'url': 'https://shop.com/p/AAA', 'keywords': 'sebenza', 'maker': ''}
    drop = {'url': 'https://shop.com/p/BBB', 'source': 'shop.com (user)',
            'products': [{'title': 'Sebenza', 'vendor': 'CRK', 'available': True}]}
    # Index a matching record under the (wrong-URL) drop so an UNGUARDED fts5 path
    # WOULD leak — only the exact-URL scoping guard should suppress it. Indexed under
    # the exact drop URL the fts5 leaf queries with (record_match.query uses drop_url).
    import record_index; importlib.reload(record_index)
    record_index.index_scan(drop['url'], drop['products'])
    assert pua.matches_for_watcher_drop(watcher, drop) == []


def test_fts5_global_watch_uses_blob_path(monkeypatch, tmp_path):
    pua, db = _fts5(monkeypatch, tmp_path)
    monkeypatch.setattr(pua, 'NO_USER_ALERT_DOMAINS', set())
    watcher = {'url': '', 'keywords': 'sebenza', 'maker': 'Chris Reeve'}  # global
    drop = {'url': 'https://shop.com/c/all', 'source': 'curated',
            'products': [{'title': 'Large Sebenza', 'vendor': 'Chris Reeve', 'available': True}]}
    assert 'sebenza' in pua.matches_for_watcher_drop(watcher, drop)
