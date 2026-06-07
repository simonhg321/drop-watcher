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
