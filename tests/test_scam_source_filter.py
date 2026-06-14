from scam_source_filter import Product, score_source


def _scam_catalog():
    # The knifesupplycenter.com catalog: uniform deep discount + leaked BHQ SKU.
    return [
        Product("Sebenza 31 Lunar Landing CGG", 575.0, 115.0,
                ["https://x/Chris-Reeve-BHQ-94298-jr-large.webp"]),
        Product("L-Hand Sebenza 31 Raindrop Damascus", 650.0, 130.0, []),
        Product("Impofu Fixed Blade LE", 600.0, 120.0, []),
        Product("Small Sebenza 31 Purple Cross", 525.0, 105.0, []),
        Product("L-Hand Sebenza 31 Ladder Damascus", 750.0, 150.0, []),
    ]


def test_scam_catalog_quarantines():
    v = score_source("knifesupplycenter.com", _scam_catalog(), domain_age_months=4)
    assert v.action == "quarantine"
    assert v.score >= 5


def test_legit_catalog_ingests():
    legit = [
        Product("Sebenza 31", 425.0, 425.0, []),
        Product("Umnumzaan", 450.0, 410.0, []),
        Product("Mnandi", 400.0, 375.0, []),
        Product("Inkosi", 470.0, 470.0, []),
        Product("Inyoni", 430.0, 430.0, []),
    ]
    v = score_source("legitknives.com", legit)
    assert v.action == "ingest"
