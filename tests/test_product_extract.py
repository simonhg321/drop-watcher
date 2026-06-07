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


def test_from_product_cards_drops_cross_site_url():
    html = '''<html><body>
    <div class="card"><a href="https://phishing.example/products/free-knife">Free Knife</a><span>$1</span></div>
    <div class="card"><a href="/products/real-knife">Real Knife</a><span>$100</span></div>
    </body></html>'''
    items = product_extract.from_product_cards(html, "https://dealer.com")
    urls = [i["url"] for i in items]
    assert all("phishing.example" not in u for u in urls)
    assert any(u == "https://dealer.com/products/real-knife" for u in urls)


def test_from_structured_data_drops_cross_site_url():
    html = '''<html><head><script type="application/ld+json">
    {"@type":"Product","name":"Evil","url":"https://phishing.example/p/x",
     "offers":{"price":"1","availability":"InStock"}}</script>
    <script type="application/ld+json">
    {"@type":"Product","name":"Good","url":"/products/good","offers":{"price":"9","availability":"InStock"}}
    </script></head></html>'''
    items = product_extract.from_structured_data(html, "https://dealer.com")
    titles = {i["title"] for i in items}
    assert "Evil" not in titles
    assert "Good" in titles


def test_from_product_cards_allows_www_subdomain_same_site():
    # same_site treats www / bare domain as same site — must NOT be dropped.
    html = '''<html><body><div class="card">
    <a href="https://www.dealer.com/products/real-knife">Real Knife</a><span>$5</span></div></body></html>'''
    items = product_extract.from_product_cards(html, "https://dealer.com")
    assert any("/products/real-knife" in i["url"] for i in items)


import yaml


def test_sources_extract_hints_shape_is_optional_dict():
    # A source with hints parses into a dict under 'extract'; absence is fine.
    doc = yaml.safe_load("""
    - name: Stubborn Dealer
      url: https://stubborn.example
      extract:
        card: li.product
        title: .name
        link: a.url
        price: .cost
    - name: Normal Dealer
      url: https://normal.example
    """)
    assert doc[0]['extract']['card'] == 'li.product'
    assert doc[1].get('extract') is None


# ── Bug fix: tier-3 title quality + bogus $0.00 price ───────────────────────

def test_from_product_cards_image_anchor_title_falls_back_to_slug():
    # Image-anchor BEFORE text-anchor for the same product (Lamnia pattern). The image
    # anchor's "text" is an image URL; must NOT become the title — fall back to a slug-
    # derived human name (or the text anchor's name), never a URL.
    html = '''<html><body>
    <div class="card">
      <a href="/en/p/121417/knives/microtech-socom-elite-orange">https://x.com/images/200x200/microtech.jpg</a>
      <a href="/en/p/121417/knives/microtech-socom-elite-orange">Microtech Socom Elite Orange</a>
    </div></body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    assert len(items) == 1
    t = items[0]["title"]
    assert not t.startswith("http"), f"title is a URL: {t}"
    assert "Microtech" in t


def test_from_product_cards_title_slug_fallback_when_only_image_anchor():
    # Only an image-anchor exists (no text sibling) → derive title from the URL slug.
    html = '''<html><body><div class="card">
      <a href="/en/p/118377/knives/trc-apocalypse-prime-elmax"><img src="/images/x.jpg"></a>
    </div></body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    assert len(items) == 1
    t = items[0]["title"]
    assert not t.startswith("http")
    assert "Trc" in t or "Apocalypse" in t.title() or "apocalypse" in t.lower()


def test_from_product_cards_drops_bogus_zero_price():
    html = '''<html><body><div class="card">
      <a href="/products/widget">Widget Knife</a><span class="price">$0.00</span></div></body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    assert items[0]["price"] == ""   # placeholder 0.00 not emitted


def test_from_product_cards_single_anchor_card_price_is_per_card():
    # Two single-<a>-per-card products in one grid with DIFFERENT prices. Price must
    # be scoped per card, not leaked from the first card to the second.
    html = '''<html><body><div class="grid">
      <a href="/en/p/1/microtech-socom"><span>Microtech Socom</span><span>$405.24</span></a>
      <a href="/en/p/2/cold-steel-srk"><span>Cold Steel SRK</span><span>$42.99</span></a>
    </div></body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    by = {i["title"]: i for i in items}
    # titles may be slug-derived; match by URL instead to be robust
    by_url = {i["url"]: i for i in items}
    socom = by_url["https://x.com/en/p/1/microtech-socom"]
    srk = by_url["https://x.com/en/p/2/cold-steel-srk"]
    assert socom["price"] == "405.24"
    assert srk["price"] == "42.99", f"price leaked across cards: {srk['price']}"


def test_from_product_cards_sibling_price_still_works():
    # Multi-element card (price is a SIBLING of the link anchor, anchor text has no price)
    # must still resolve via the container fallback.
    html = '''<html><body><div class="card">
      <a href="/products/widget">Widget Knife</a><span class="price">$88.00</span>
    </div></body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    assert items[0]["price"] == "88.00"


def test_from_product_cards_single_anchor_sold_out_is_per_card():
    html = '''<html><body><div class="grid">
      <a href="/en/p/1/in-stock-knife"><span>In Stock Knife</span><span>$10.00</span></a>
      <a href="/en/p/2/gone-knife"><span>Gone Knife</span><span>$20.00</span><span>Sold out</span></a>
    </div></body></html>'''
    items = product_extract.from_product_cards(html, "https://x.com")
    by_url = {i["url"]: i for i in items}
    assert by_url["https://x.com/en/p/1/in-stock-knife"]["available"] is True
    assert by_url["https://x.com/en/p/2/gone-knife"]["available"] is False, "sold-out leaked across cards"
