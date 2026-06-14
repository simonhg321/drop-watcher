import os
import tempfile
import importlib


def _fresh():
    d = tempfile.mkdtemp()
    os.environ["DW_DB"] = os.path.join(d, "t.db")
    import db
    importlib.reload(db)
    import record_index
    importlib.reload(record_index)
    return db, record_index


def test_index_scan_inserts_only_instock_and_is_searchable():
    db, ri = _fresh()
    products = [
        {"title": "RMJ x Strider Axe", "vendor": "RMJ", "tags": [], "url": "u1",
         "price": "300", "available": True},
        {"title": "Strider SMF", "vendor": "Strider", "tags": [], "url": "u2",
         "price": "400", "available": True},
        {"title": "Sold Out Knife", "vendor": "X", "tags": [], "url": "u3",
         "price": "1", "available": False},
    ]
    ri.index_scan("https://shop.com/collections/all", products)
    with db.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM product_records").fetchone()["n"]
    assert n == 2  # sold-out excluded

    rows = ri.search_source("https://shop.com/collections/all", "Strider")
    titles = {r["title"] for r in rows}
    assert "RMJ x Strider Axe" in titles and "Strider SMF" in titles


def test_index_scan_rebuilds_per_source():
    db, ri = _fresh()
    src = "https://shop.com/collections/all"
    ri.index_scan(src, [{"title": "A", "vendor": "", "tags": [], "url": "a",
                         "price": "1", "available": True}])
    ri.index_scan(src, [{"title": "B", "vendor": "", "tags": [], "url": "b",
                         "price": "1", "available": True}])
    with db.get_db() as conn:
        titles = {r["title"] for r in conn.execute(
            "SELECT title FROM product_records WHERE source_url=?", (src,)).fetchall()}
    assert titles == {"B"}  # old scan replaced, not accumulated
