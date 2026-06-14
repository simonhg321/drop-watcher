"""
scam_source_filter.py — heuristic quarantine for generated-catalog scam storefronts.

Designed for the Billboard scraper model: you scrape a SOURCE (one domain) and get
back a list of products. This evaluates the WHOLE source at once, because the
strongest signal — uniform discounting — only shows up across the catalog, not in
any single product.

Drop into the scraper between fetch and ingest:

    verdict = score_source(domain, products)
    if verdict.action == "quarantine":
        log.warning("quarantined %s: %s", domain, verdict.reasons)
        continue  # do not ingest, do not alert users

No external deps for the core checks. WHOIS age is an optional hook (see note).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from statistics import pstdev, median
import re

# --- knobs (tune against your own corpus) ----------------------------------

UNIFORM_DISCOUNT_MAX_STDEV = 0.03   # near-zero variance in discount ratio = bot
SUSPICIOUS_DISCOUNT_RATIO  = 0.35   # sale/orig below this is implausible for CRK-tier
MIN_CATALOG_FOR_UNIFORMITY = 4      # need a few products to judge variance
DOMAIN_AGE_MONTHS_MIN      = 6      # younger than this is a risk factor, not a verdict

# Known-retailer SKU tokens that leak in stolen image filenames.
# Extend as you find them. These are the giveaway that catalog+images were lifted.
RETAILER_SKU_TOKENS = [
    r"BHQ-?\d+",      # BladeHQ
    r"KC-?\d+",       # KnifeCenter (varies; verify before trusting)
    r"BRK-?\d+",      # Blade HQ alt
    r"GPK-?\d+",      # GPKnives
]
_SKU_RE = re.compile("|".join(RETAILER_SKU_TOKENS), re.IGNORECASE)

# Free-worldwide-shipping threshold that's nonsensical for high-value goods.
FREE_WW_SHIPPING_RE = re.compile(r"free\s+worldwide\s+shipping", re.IGNORECASE)
LOW_FREE_SHIP_THRESHOLD = 50.0  # "free worldwide over $30" on $115 knives = absurd


@dataclass
class Product:
    title: str
    original_price: float | None      # crossed-out / MSRP if present
    sale_price: float | None          # current price
    image_urls: list[str] = field(default_factory=list)
    raw_html: str = ""                # optional, for shipping-string sniff


@dataclass
class Verdict:
    action: str                       # "ingest" | "review" | "quarantine"
    score: int                        # higher = more suspicious
    reasons: list[str] = field(default_factory=list)


def _discount_ratios(products: list[Product]) -> list[float]:
    ratios = []
    for p in products:
        if p.original_price and p.sale_price and p.original_price > 0:
            ratios.append(p.sale_price / p.original_price)
    return ratios


def score_source(
    domain: str,
    products: list[Product],
    domain_age_months: float | None = None,  # pass from WHOIS hook if you have it
) -> Verdict:
    score = 0
    reasons: list[str] = []

    ratios = _discount_ratios(products)

    # 1) Uniform discount across the catalog — the single best signal.
    #    A real sale has scatter; a multiplier script produces a flat line.
    if len(ratios) >= MIN_CATALOG_FOR_UNIFORMITY:
        spread = pstdev(ratios)
        med = median(ratios)
        if spread < UNIFORM_DISCOUNT_MAX_STDEV:
            score += 4
            reasons.append(
                f"uniform discount across {len(ratios)} products "
                f"(median ratio {med:.2f}, stdev {spread:.3f})"
            )
            # extra weight if that uniform ratio is also implausibly deep
            if med < SUSPICIOUS_DISCOUNT_RATIO:
                score += 2
                reasons.append(f"uniform ratio is implausibly deep ({med:.0%} of MSRP)")

    # 2) Stolen images — retailer SKU tokens in filenames.
    leaked = 0
    for p in products:
        if any(_SKU_RE.search(u) for u in p.image_urls):
            leaked += 1
    if leaked:
        score += 3
        reasons.append(f"{leaked} product(s) reuse a known-retailer SKU token in image filenames")

    # 3) Free-worldwide-shipping on high-value goods at a tiny threshold.
    for p in products:
        if p.raw_html and FREE_WW_SHIPPING_RE.search(p.raw_html):
            # find a "$NN" threshold near the phrase; cheap sniff
            m = re.search(r"over\s*\$?\s*(\d+)", p.raw_html, re.IGNORECASE)
            thresh = float(m.group(1)) if m else None
            if thresh is not None and thresh <= LOW_FREE_SHIP_THRESHOLD \
               and (p.sale_price or 0) > 80:
                score += 2
                reasons.append(
                    f"free worldwide shipping over ${thresh:.0f} on a "
                    f"${p.sale_price:.0f} item"
                )
                break

    # 4) Young domain — risk factor, never a verdict on its own.
    if domain_age_months is not None and domain_age_months < DOMAIN_AGE_MONTHS_MIN:
        score += 1
        reasons.append(f"domain only {domain_age_months:.1f} months old")

    # --- decide -------------------------------------------------------------
    if score >= 5:
        action = "quarantine"
    elif score >= 3:
        action = "review"
    else:
        action = "ingest"

    return Verdict(action=action, score=score, reasons=reasons)


if __name__ == "__main__":
    # The knifesupplycenter.com catalog you found, as a sanity check.
    catalog = [
        Product("Sebenza 31 Lunar Landing CGG", 575.0, 115.0,
                ["https://x/Chris-Reeve-...-BHQ-94298-jr-large.webp"]),
        Product("L-Hand Sebenza 31 Raindrop Damascus", 650.0, 130.0, []),
        Product("Impofu Fixed Blade LE",        600.0, 120.0, []),
        Product("Small Sebenza 31 Purple Cross", 525.0, 105.0, []),
        Product("L-Hand Sebenza 31 Ladder Damascus", 750.0, 150.0, []),
    ]
    v = score_source("knifesupplycenter.com", catalog, domain_age_months=4)
    print(v.action.upper(), "score:", v.score)
    for r in v.reasons:
        print("  -", r)
