"""Tests for bin/dualrun_matcher.classify — the pure blob-vs-fts5 bucketing fn.

There is no clean unit test for the whole-DB diff tool, so we test the factored-out
classify() against a tiny in-memory scenario: one URL-scoped, maker-less watcher and
three drops engineered to land in each interesting bucket.

How the two matchers diverge for a URL-scoped maker-less watch:
  - blob: keywords_match against the drop's searchable text (prose + product titles)
  - fts5: record_match.query against the product_records index for that source URL
So we control the bucket by what's in the drop text vs. what's in the fts5 index.

The tool must be READ-ONLY; classify() only reads + computes, never writes.
"""
import importlib
import os
import sys
import tempfile

import pytest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
ROOT = os.path.dirname(BIN)
for p in (ROOT, BIN):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def env(monkeypatch):
    """Fresh isolated DB + reloaded modules; DW_MATCHER left UNSET (default blob).

    classify() toggles DW_MATCHER itself per call and restores it, so the fixture
    asserts nothing leaks: after classify the env var must be back to unset.
    """
    d = tempfile.mkdtemp()
    monkeypatch.setenv("DW_DB", os.path.join(d, "t.db"))
    monkeypatch.delenv("DW_MATCHER", raising=False)
    import paths; importlib.reload(paths)
    import db; importlib.reload(db)
    import record_index; importlib.reload(record_index)
    import record_match; importlib.reload(record_match)
    import per_user_alerter as pua; importlib.reload(pua)
    import dualrun_matcher as dr; importlib.reload(dr)
    # dualrun imported its own `db`/`pua` references; make sure they're the reloaded ones.
    dr.db = db
    dr.pua = pua
    monkeypatch.setattr(pua, "NO_USER_ALERT_DOMAINS", set())
    return dr, db, record_index, pua


SRC = "https://shop.com/collections/all"


def _drop(text, products):
    """A curated (non-user) URL-scoped drop on shop.com.

    `text` goes into page_summary (part of drop_prose_text, which the blob path
    searches); products feed both the searchable titles and (when indexed) fts5.
    """
    return {
        "url": SRC,
        "source": "curated",
        "page_summary": text,
        "notable_items": [],
        "products": products,
    }


def _instock(title):
    return {"title": title, "vendor": "", "tags": [], "url": "u",
            "price": "1", "available": True}


def test_classify_both(env):
    dr, db, ri, pua = env
    watcher = {"id": 1, "url": SRC, "keywords": "sebenza", "maker": ""}
    # Keyword in drop text (blob match) AND indexed in-stock (fts5 match).
    ri.index_scan(SRC, [_instock("Large Sebenza 31")])
    drop = _drop("Large Sebenza 31 in stock now", [_instock("Large Sebenza 31")])
    bucket, blob, fts5 = dr.classify(watcher, drop)
    assert bucket == "both"
    assert blob and fts5
    assert os.environ.get("DW_MATCHER") is None  # env restored, nothing leaked


def test_classify_blob_only(env):
    dr, db, ri, pua = env
    watcher = {"id": 2, "url": SRC, "keywords": "mnandi", "maker": ""}
    # Keyword present in drop prose (blob fires) but index has NO matching record
    # (fts5 stays empty) — flipping to fts5 would stop this alert: a possible miss.
    ri.index_scan(SRC, [_instock("Some Unrelated Knife")])
    drop = _drop("Mnandi just dropped", [])
    bucket, blob, fts5 = dr.classify(watcher, drop)
    assert bucket == "blob_only"
    assert blob and not fts5
    assert os.environ.get("DW_MATCHER") is None


def test_classify_fts5_only(env):
    dr, db, ri, pua = env
    watcher = {"id": 3, "url": SRC, "keywords": "inkosi", "maker": ""}
    # Index HAS a matching in-stock record (fts5 fires) but the drop's searchable
    # text does NOT mention the keyword (blob misses) — fts5 would newly alert.
    ri.index_scan(SRC, [_instock("Large Inkosi Insingo")])
    drop = _drop("New arrivals this week", [])
    bucket, blob, fts5 = dr.classify(watcher, drop)
    assert bucket == "fts5_only"
    assert fts5 and not blob
    assert os.environ.get("DW_MATCHER") is None


def test_classify_neither(env):
    dr, db, ri, pua = env
    watcher = {"id": 4, "url": SRC, "keywords": "umnumzaan", "maker": ""}
    ri.index_scan(SRC, [_instock("Unrelated")])
    drop = _drop("nothing relevant here", [])
    bucket, blob, fts5 = dr.classify(watcher, drop)
    assert bucket == "neither"
    assert not blob and not fts5
