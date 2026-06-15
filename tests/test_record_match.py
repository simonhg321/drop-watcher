import os, tempfile, importlib


def _fresh():
    d = tempfile.mkdtemp(); os.environ['DW_DB'] = os.path.join(d, 't.db')
    import db; importlib.reload(db)
    import record_index; importlib.reload(record_index)
    import record_match; importlib.reload(record_match)
    return db, record_index, record_match


SRC = "https://monkeyedge.com/collections/all"
CATALOG = [
    {"title": "RMJ x Strider BS Axe", "vendor": "RMJ", "tags": [], "url": "axe",
     "price": "300", "available": True},
    {"title": "VZ Grips Strider Fixed-Blade grips", "vendor": "VZ Grips", "tags": [],
     "url": "grips", "price": "40", "available": True},
    {"title": "Strider SMF", "vendor": "Strider", "tags": [], "url": "smf",
     "price": "400", "available": True},
    {"title": "Umnumzaan Tanto", "vendor": "Chris Reeve", "tags": ["Magnacut"],
     "url": "umz", "price": "500", "available": True},
]


def test_maker_watch_suppresses_cross_brand_false_positive():
    db, ri, rm = _fresh(); ri.index_scan(SRC, CATALOG)
    # Maker=Strider, keyword=strider → must match only the real Strider SMF,
    # NOT the RMJ axe or the VZ grips (the famous false positive).
    watcher = {"url": SRC, "keywords": "strider", "maker": "Strider"}
    hits = rm.query(watcher, source_url=SRC)
    urls = {h["url"] for h in hits}
    assert urls == {"smf"}


def test_makerless_watch_matches_title_token():
    db, ri, rm = _fresh(); ri.index_scan(SRC, CATALOG)
    watcher = {"url": SRC, "keywords": "umnumzaan", "maker": ""}
    hits = rm.query(watcher, source_url=SRC)
    assert {h["url"] for h in hits} == {"umz"}


def test_makerless_generic_keyword_does_not_bleed_store_wide():
    db, ri, rm = _fresh()
    ri.index_scan(SRC, CATALOG + [
        {"title": "Scapegoat Compact", "vendor": "X", "tags": [], "url": "sg",
         "price": "100", "available": True}])
    # keyword 'compact' matches only the product literally titled Compact —
    # not the whole store (the stale-blob bug).
    watcher = {"url": SRC, "keywords": "compact", "maker": ""}
    hits = rm.query(watcher, source_url=SRC)
    assert {h["url"] for h in hits} == {"sg"}


def test_query_matches_when_watcher_url_differs_by_scheme_www_slash():
    db, ri, rm = _fresh()
    # index under the canonical scan-time spelling...
    ri.index_scan("https://www.MonkeyEdge.com/collections/all/", CATALOG)
    # ...watcher carries a differently-spelled but equivalent URL.
    watcher = {"url": "http://monkeyedge.com/collections/all", "keywords": "umnumzaan",
               "maker": ""}
    hits = rm.query(watcher)
    assert {h["url"] for h in hits} == {"umz"}
