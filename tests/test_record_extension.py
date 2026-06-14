"""
test_record_extension.py — Task 2: structured records carry original_price + image_urls.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

import collection_fetch
import product_extract


def test_parse_products_captures_original_price_and_images():
    raw = [{
        "handle": "sebenza-31",
        "title": "Sebenza 31",
        "vendor": "Chris Reeve",
        "tags": ["Magnacut"],
        "images": [{"src": "https://cdn.shop/img/sebenza-1.jpg"},
                   {"src": "https://cdn.shop/img/sebenza-2.jpg"}],
        "variants": [{"available": True, "price": "425.00", "compare_at_price": "475.00"}],
    }]
    out = collection_fetch._parse_products(raw, "https://example.com/collections/all")
    rec = out[0]
    assert rec["price"] == "425.00"
    assert rec["original_price"] == "475.00"
    assert rec["image_urls"] == ["https://cdn.shop/img/sebenza-1.jpg",
                                 "https://cdn.shop/img/sebenza-2.jpg"]


def test_parse_products_defaults_when_absent():
    raw = [{"handle": "x", "title": "X", "vendor": "", "tags": "",
            "variants": [{"available": True, "price": "10.00"}]}]
    rec = collection_fetch._parse_products(raw, "https://example.com")[0]
    assert rec["original_price"] is None
    assert rec["image_urls"] == []


def test_jsonld_carries_new_fields_or_defaults():
    html = '''<script type="application/ld+json">
    {"@type":"Product","name":"Sebenza 31","brand":"Chris Reeve",
     "image":"https://cdn/sebenza.jpg",
     "offers":{"@type":"Offer","price":"425.00","availability":"http://schema.org/InStock"}}
    </script>'''
    out = product_extract.from_structured_data(html, "https://example.com/products/sebenza-31")
    assert out, "expected one product"
    assert "original_price" in out[0]
    assert "image_urls" in out[0]
