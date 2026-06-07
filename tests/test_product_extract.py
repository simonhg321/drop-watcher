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


# ── Task 3: from_product_cards (tier 3 — generic + hints) ───────────────────

# Lamnia-style: server-rendered /p/ anchors with prices nearby.
CARDS_HTML = """
<html><body>
<div class="grid">
  <div class="card"><a href="/en/p/121417/microtech-socom-elite-orange">Microtech Socom Elite Orange</a>
    <span class="price">$405.24</span></div>
  <div class="card"><a href="/en/p/118377/trc-apocalypse-prime">TRC Apocalypse Prime</a>
    <span class="price">$312.00</span><span>Sold out</span></div>
</div>
<a href="/cart">Cart</a>
</body></html>
"""

HINTS_HTML = """
<html><body>
<li class="prod"><h3 class="t">Widget A</h3><a class="lnk" href="/shop/widget-a">link</a>
  <em class="p">$10.00</em></li>
<li class="prod"><h3 class="t">Widget B</h3><a class="lnk" href="/shop/widget-b">link</a>
  <em class="p">$20.00</em></li>
</body></html>
"""


def test_from_product_cards_generic():
    items = product_extract.from_product_cards(CARDS_HTML, "https://www.lamnia.com")
    by_title = {i["title"]: i for i in items}
    assert by_title["Microtech Socom Elite Orange"]["url"] == \
        "https://www.lamnia.com/en/p/121417/microtech-socom-elite-orange"
    assert by_title["Microtech Socom Elite Orange"]["price"] == "405.24"
    assert by_title["Microtech Socom Elite Orange"]["available"] is True
    assert by_title["TRC Apocalypse Prime"]["available"] is False  # "Sold out" nearby
    # The /cart nav anchor must NOT become a product.
    assert all("/cart" not in i["url"] for i in items)


def test_from_product_cards_with_hints():
    hints = {"card": "li.prod", "title": "h3.t", "link": "a.lnk", "price": "em.p"}
    items = product_extract.from_product_cards(HINTS_HTML, "https://x.com", hints=hints)
    by_title = {i["title"]: i for i in items}
    assert by_title["Widget A"]["url"] == "https://x.com/shop/widget-a"
    assert by_title["Widget B"]["price"] == "20.00"


def test_from_product_cards_empty_when_no_products():
    assert product_extract.from_product_cards(
        "<html><body><a href='/about'>About</a></body></html>", "https://x.com") == []


def test_from_product_cards_image_only_card_uses_alt():
    html = '''<html><body>
    <div class="card"><a href="/products/microtech-ultratech"><img alt="Microtech Ultratech Bronze"></a>
      <span class="price">$300.00</span></div>
    </body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    assert any(i["title"] == "Microtech Ultratech Bronze" and
               i["url"].endswith("/products/microtech-ultratech") for i in items)


def test_from_product_cards_aria_label_fallback():
    html = '''<html><body>
    <div class="card"><a href="/products/widget" aria-label="Cool Widget Knife"></a></div>
    </body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    assert any(i["title"] == "Cool Widget Knife" for i in items)


def test_from_hints_skips_bad_href():
    hints = {"card": "div.c", "link": "a", "title": "a"}
    html = '''<html><body>
    <div class="c"><a href="/cart">Cart</a></div>
    <div class="c"><a href="/products/real">Real Product</a></div>
    </body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com", hints=hints)
    assert all("/cart" not in i["url"] for i in items)
    assert any(i["title"] == "Real Product" for i in items)


# ── Task 4: fetch_collection wired to structured extractors ─────────────────
import collection_fetch as cf


def test_fetch_collection_uses_product_cards_for_non_shopify():
    # fetch_page stub: Shopify products.json 404s (not Shopify), HTML returns cards.
    def fake_fetch(url, ssl_permissive=False):
        if url.endswith('/products.json'):
            return None
        return CARDS_HTML
    text, products, candidates = cf.fetch_collection("https://www.lamnia.com", fake_fetch)
    titles = {p['title'] for p in (products or [])}
    assert "Microtech Socom Elite Orange" in titles
    # Structured success → no fuzzy candidates emitted (alerter trusts products).
    assert candidates == []


def test_fetch_collection_falls_back_to_candidates_when_unstructured():
    def fake_fetch(url, ssl_permissive=False):
        if url.endswith('/products.json'):
            return None
        return "<html><body><a href='/widget-thing-deep-slug'>Widget Thing</a></body></html>"
    text, products, candidates = cf.fetch_collection("https://x.com", fake_fetch)
    assert products is None          # nothing structured found
    assert isinstance(candidates, list)  # legacy fuzzy candidates still available
