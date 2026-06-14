import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

import scam_gate


def test_to_products_maps_records():
    records = [{"title": "Sebenza", "price": "115.00", "original_price": "575.00",
                "image_urls": ["https://x/BHQ-94298.webp"]}]
    prods = scam_gate.to_products(records)
    assert prods[0].title == "Sebenza"
    assert prods[0].sale_price == 115.0
    assert prods[0].original_price == 575.0
    assert prods[0].image_urls == ["https://x/BHQ-94298.webp"]


def test_evaluate_flags_scam(monkeypatch):
    scam_records = [
        {"title": "Sebenza 31 Lunar Landing", "price": "115.00", "original_price": "575.00",
         "image_urls": ["https://x/Chris-Reeve-BHQ-94298-jr.webp"]},
        {"title": "Raindrop Damascus", "price": "130.00", "original_price": "650.00", "image_urls": []},
        {"title": "Impofu LE", "price": "120.00", "original_price": "600.00", "image_urls": []},
        {"title": "Purple Cross", "price": "105.00", "original_price": "525.00", "image_urls": []},
        {"title": "Ladder Damascus", "price": "150.00", "original_price": "750.00", "image_urls": []},
    ]
    monkeypatch.setattr(scam_gate, "_fetch_records",
                        lambda sample_url, fetch_page, log=None: scam_records)
    v = scam_gate.evaluate("knifesupplycenter.com", "https://knifesupplycenter.com",
                           fetch_page=lambda u, s=False: "", log=None)
    assert v.action == "quarantine"


def test_evaluate_passes_legit(monkeypatch):
    legit = [{"title": f"Knife {i}", "price": "425.00", "original_price": None, "image_urls": []}
             for i in range(6)]
    monkeypatch.setattr(scam_gate, "_fetch_records",
                        lambda sample_url, fetch_page, log=None: legit)
    v = scam_gate.evaluate("legit.com", "https://legit.com", fetch_page=lambda u, s=False: "")
    assert v.action == "ingest"
