import os
import sys

# ── Setup paths so imports work ──────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

import collection_fetch


def test_shopify_products_url_collection():
    assert collection_fetch.shopify_products_url(
        "https://southernedges.com/collections/thursday-drop"
    ) == "https://southernedges.com/collections/thursday-drop/products.json"


def test_shopify_products_url_root_fallback():
    # Homepage / non-collection URL must fall back to the site-root products.json
    # so homepage-configured Shopify dealers still hit the structured path.
    assert collection_fetch.shopify_products_url(
        "https://southernedges.com"
    ) == "https://southernedges.com/products.json"
    assert collection_fetch.shopify_products_url(
        "https://southernedges.com/"
    ) == "https://southernedges.com/products.json"


def test_shopify_products_url_requires_host():
    assert collection_fetch.shopify_products_url("not-a-url") is None


# ── Task 2: from_structured_data (JSON-LD tier 2) ────────────────────────────
import product_extract

JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Chris Reeve Inyoni",
 "url":"/products/chris-reeve-inyoni","offers":{"@type":"Offer","price":"425.00",
 "availability":"https://schema.org/InStock"}}
</script>
<script type="application/ld+json">
{"@type":"Product","name":"Sold Out Knife","url":"/products/sold-out",
 "offers":{"price":"100.00","availability":"https://schema.org/OutOfStock"}}
</script>
</head><body></body></html>
"""


def test_from_structured_data_parses_jsonld():
    items = product_extract.from_structured_data(JSONLD_HTML, "https://x.com")
    by_title = {i["title"]: i for i in items}
    assert by_title["Chris Reeve Inyoni"]["url"] == "https://x.com/products/chris-reeve-inyoni"
    assert by_title["Chris Reeve Inyoni"]["available"] is True
    assert by_title["Chris Reeve Inyoni"]["price"] == "425.00"
    assert by_title["Sold Out Knife"]["available"] is False


def test_from_structured_data_empty_when_none():
    assert product_extract.from_structured_data("<html><body>no schema</body></html>", "https://x.com") == []


def test_from_structured_data_offers_list_any_in_stock():
    html = '''<html><head><script type="application/ld+json">
    {"@type":"Product","name":"Multi Variant Knife","url":"/products/mvk",
     "offers":[{"@type":"Offer","price":"10.00","availability":"https://schema.org/OutOfStock"},
               {"@type":"Offer","price":"12.00","availability":"https://schema.org/InStock"}]}
    </script></head></html>'''
    items = product_extract.from_structured_data(html, "https://x.com")
    assert items[0]["available"] is True          # any offer in stock → available
    assert items[0]["price"] == "10.00"            # price from first offer


def test_from_structured_data_graph_wrapper():
    html = '''<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
       {"@type":"WebSite","name":"x"},
       {"@type":"Product","name":"Graph Knife","url":"/products/gk",
        "offers":{"price":"99.00","availability":"InStock"}}]}
    </script></head></html>'''
    items = product_extract.from_structured_data(html, "https://x.com")
    titles = {i["title"] for i in items}
    assert "Graph Knife" in titles
    assert next(i for i in items if i["title"] == "Graph Knife")["available"] is True


def test_from_structured_data_malformed_block_skipped():
    html = '''<html><head>
    <script type="application/ld+json">{ this is not json }</script>
    <script type="application/ld+json">{"@type":"Product","name":"Valid Knife","url":"/p/v",
      "offers":{"price":"5.00","availability":"InStock"}}</script>
    </head></html>'''
    items = product_extract.from_structured_data(html, "https://x.com")
    assert {i["title"] for i in items} == {"Valid Knife"}   # malformed skipped, valid kept
