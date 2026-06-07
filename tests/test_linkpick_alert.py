"""Regression tests for deep-link resolution on alerts.

Bug (2026-06-03): an alert for "Ubiquiti UVC-G6-180-W Camera (White)" linked to
the G6 *Pro 360* product page because the link was resolved from the watch
KEYWORD ("White 360 camera") whose token "360" matched a different product's
slug. The link must instead resolve against the specific matched product.
"""
import linkpick

# Representative slice of the real store.ui.com candidate links from the drop.
UI_CANDS = [
    {"text": "G6 Pro Dome", "href": "https://store.ui.com/us/en/category/cameras-dome-turret/products/uvc-g6-pro-dome"},
    {"text": "G6 Pro 360", "href": "https://store.ui.com/us/en/category/cameras-dome-turret/products/uvc-g6-pro-360"},
    {"text": "G6 Dome", "href": "https://store.ui.com/us/en/category/cameras-dome-turret/products/uvc-g6-dome"},
    {"text": "G6 180", "href": "https://store.ui.com/us/en/category/cameras-dome-turret/products/uvc-g6-180"},
    {"text": "AI 360", "href": "https://store.ui.com/us/en/category/cameras-dome-turret/products/uvc-ai-360"},
]

SEBENZA_CANDS = [
    {"text": "Chris Reeve Inkosi", "href": "https://x.com/products/chris-reeve-inkosi"},
    {"text": "Chris Reeve Sebenza 31", "href": "https://x.com/products/chris-reeve-sebenza-31"},
    {"text": "Chris Reeve Umnumzaan", "href": "https://x.com/products/chris-reeve-umnumzaan"},
]


def test_strip_status_prefix():
    assert linkpick.strip_status_prefix("IN STOCK — Ubiquiti G6-180") == "Ubiquiti G6-180"
    assert linkpick.strip_status_prefix("NOTIFY ME — X") == "X"
    assert linkpick.strip_status_prefix("Sold Out: Widget") == "Widget"
    assert linkpick.strip_status_prefix("Plain Product Name") == "Plain Product Name"


def test_resolve_alert_link_uses_matched_product_not_keyword():
    # The bug: keyword "White 360 camera" pulled the link to uvc-g6-pro-360.
    url = linkpick.resolve_alert_link(
        UI_CANDS,
        notable_items=["NOTIFY ME — Ubiquiti UVC-G6-180-W Camera (White)"],
        keywords=["White 360 camera"],
        makers=["Ubiquiti"],
    )
    assert url.endswith("/uvc-g6-180"), f"linked to wrong product: {url}"


def test_resolve_alert_link_picks_matched_notable_among_many():
    # Multi-product dealer drop: must link to the matched product, not the first.
    url = linkpick.resolve_alert_link(
        SEBENZA_CANDS,
        notable_items=["Chris Reeve Inkosi", "IN STOCK — Chris Reeve Sebenza 31", "Chris Reeve Umnumzaan"],
        keywords=["Sebenza"],
        makers=["Chris Reeve"],
    )
    assert url.endswith("/chris-reeve-sebenza-31"), f"linked to wrong product: {url}"


def test_resolve_alert_link_falls_back_to_keyword_when_no_notables():
    url = linkpick.resolve_alert_link(
        SEBENZA_CANDS, notable_items=[], keywords=["Sebenza"], makers=["Chris Reeve"])
    assert url.endswith("/chris-reeve-sebenza-31")


def test_resolve_alert_link_none_when_nothing_resolves():
    assert linkpick.resolve_alert_link(
        UI_CANDS, notable_items=["Random Unrelated Thing"], keywords=["nonexistent"], makers=[]) is None


def test_resolve_alert_candidate_returns_text_and_href():
    c = linkpick.resolve_alert_candidate(
        UI_CANDS,
        notable_items=["IN STOCK — Ubiquiti UVC-G6-180-W Camera (White)"],
        keywords=["White 360 camera"], makers=["Ubiquiti"])
    assert c["href"].endswith("/uvc-g6-180")
    assert c["text"] == "G6 180"   # title + link now agree, both the right product


# Real #6289 shape: no candidate is actually the queried item, but generic tokens
# ("fixed","blade") let a wrong product score on token overlap. Must return None.
NO_MATCH_CANDS = [
    {"text": "Half-Face Blades Ringstrike Fixed Blade",
     "href": "https://southernedges.com/products/half-face-blades-ringstrike-fixed-blade"},
    {"text": "Chris Reeve Small Sebenza 31 Forever Flag",
     "href": "https://southernedges.com/products/chris-reeve-small-sebenza-31-forever-flag"},
]


def test_best_candidate_returns_none_below_floor():
    # "Lile DOT Fixed Blade Knife" has no real candidate here → must not mislink.
    assert linkpick.best_candidate(NO_MATCH_CANDS, "Lile DOT Fixed Blade Knife") is None


def test_best_candidate_still_resolves_strong_match():
    # A genuine match (distinctive tokens present) must still resolve above the floor.
    c = linkpick.best_candidate(NO_MATCH_CANDS, "Chris Reeve Small Sebenza 31 Forever Flag")
    assert c is not None
    assert c["href"].endswith("/chris-reeve-small-sebenza-31-forever-flag")


# ---------------------------------------------------------------------------
# Task 7: end-to-end #6289 regression — resolve_drop_items
# ---------------------------------------------------------------------------
import per_user_alerter as pua


def test_resolve_drop_items_structured_deeplinks_correctly():
    drop = {
        "url": "https://southernedges.com",
        "source": "Southern Edges",
        "products": [
            {"title": "Chris Reeve Large Sebenza 31 Bog Oak Magnacut",
             "url": "https://southernedges.com/products/crk-large-sebenza-31-bog-oak",
             "available": True, "tags": [], "price": "650.00"},
        ],
        "notable_items": ["Chris Reeve Large Sebenza 31 Bog Oak Magnacut - $650.00"],
        "link_candidates": [],
    }
    items = pua.resolve_drop_items(drop, ["Sebenza"])
    assert len(items) == 1
    assert items[0]["url"].endswith("/crk-large-sebenza-31-bog-oak")


def test_resolve_drop_items_unlisted_item_does_not_mislink():
    # "Lile DOT" is a notable_item but NOT in structured products and NOT a real
    # candidate → resolve must NOT return a wrong product. With empty candidates
    # (structured source), it returns [] and the email falls back to the page link.
    drop = {
        "url": "https://southernedges.com",
        "source": "Southern Edges",
        "products": [],
        "notable_items": ["Lile DOT Fixed Blade Knife - $1,600.00"],
        "link_candidates": [],   # structured source emits no fuzzy candidates
    }
    items = pua.resolve_drop_items(drop, ["Lile DOT Fixed Blade Knife"])
    assert all("half-face" not in i.get("url", "") for i in items)


# ---------------------------------------------------------------------------
# Task 8: integration regression #6289 — floor blocks wrong product on
# UNSTRUCTURED drop (no structured products, fuzzy link_candidates path)
# ---------------------------------------------------------------------------

def test_resolve_drop_items_carries_confidence():
    drop_high = {"url": "https://s.com", "source": "S",
        "products": [{"title": "Sebenza 31", "url": "https://s.com/products/sebenza-31",
                      "available": True, "tags": [], "price": "650.00", "confidence": "high"}],
        "notable_items": [], "link_candidates": []}
    items = pua.resolve_drop_items(drop_high, ["Sebenza"])
    assert items[0]["confidence"] == "high"

    drop_low = {"url": "https://s.com", "source": "S",
        "products": [{"title": "Sebenza 31", "url": "https://s.com/products/sebenza-31",
                      "available": True, "tags": [], "price": "650.00", "confidence": "low"}],
        "notable_items": [], "link_candidates": []}
    items = pua.resolve_drop_items(drop_low, ["Sebenza"])
    assert items[0]["confidence"] == "low"


import os

def test_build_alert_email_marks_low_confidence_with_thinking_emoji():
    os.environ.setdefault("DW_NKD_ENABLED", "0")
    watcher = {"name": "T", "unsubscribe_token": "tok", "id": 1}
    low_drop = {"url": "https://s.com", "source": "S", "page_summary": "",
        "products": [{"title": "Scraped Knife", "url": "https://s.com/products/scraped",
                      "available": True, "tags": [], "price": "10.00", "confidence": "low"}],
        "notable_items": [], "link_candidates": []}
    result = pua.build_alert_email(watcher, ["Scraped Knife"], low_drop)
    subject, html, text = result
    assert "🤔" in html
    assert "🤔" in text

    # High-confidence drop must NOT emit the emoji
    high_drop = {"url": "https://s.com", "source": "S", "page_summary": "",
        "products": [{"title": "Shopify Knife", "url": "https://s.com/products/shopify",
                      "available": True, "tags": [], "price": "10.00", "confidence": "high"}],
        "notable_items": [], "link_candidates": []}
    result2 = pua.build_alert_email(watcher, ["Shopify Knife"], high_drop)
    subject2, html2, text2 = result2
    assert "🤔" not in html2
    assert "🤔" not in text2


def test_resolve_drop_items_unstructured_floor_blocks_wrong_product():
    # Literal #6289: an unstructured drop (no structured products) with a bag of fuzzy
    # candidates. The queried item "Lile DOT Fixed Blade Knife" has NO real candidate;
    # only generic tokens ("fixed","blade") overlap the half-face product. The Task 6
    # confidence floor must reject it → page-link fallback, NEVER the half-face URL.
    drop = {
        "url": "https://southernedges.com",
        "source": "Southern Edges",
        # no structured products → resolve_drop_items consults link_candidates (the fuzzy path)
        "notable_items": ["Lile DOT Fixed Blade Knife - $1,600.00"],
        "link_candidates": [
            {"text": "Half-Face Blades Ringstrike Fixed Blade",
             "href": "https://southernedges.com/products/half-face-blades-ringstrike-fixed-blade"},
            {"text": "Chris Reeve Small Sebenza 31 Forever Flag",
             "href": "https://southernedges.com/products/chris-reeve-small-sebenza-31-forever-flag"},
        ],
    }
    items = pua.resolve_drop_items(drop, ["Lile DOT Fixed Blade Knife"])
    # Must not deep-link to a wrong product; page-link fallback is acceptable.
    assert all("half-face" not in i.get("url", "") for i in items)
    assert all(i.get("url", "") in ("", "https://southernedges.com") for i in items)


# ---------------------------------------------------------------------------
# Keyword-improvement prompt tests (S55)
# ---------------------------------------------------------------------------

def test_alert_uncertain_shows_keyword_hint():
    import os
    os.environ.setdefault("DW_NKD_ENABLED", "0")
    watcher = {"name": "T", "unsubscribe_token": "tok123", "id": 1}
    low_drop = {"url": "https://s.com", "source": "S", "page_summary": "",
        "products": [{"title": "Scraped Knife", "url": "https://s.com/products/scraped",
                      "available": True, "tags": [], "price": "10.00", "confidence": "low"}],
        "notable_items": [], "link_candidates": []}
    subject, html, text = pua.build_alert_email(watcher, ["Scraped Knife"], low_drop)
    assert "Better keywords mean better matches" in html
    assert "my-alerts.html?token=tok123" in html
    assert "Better keywords mean better matches" in text


def test_alert_high_confidence_no_keyword_hint():
    import os
    os.environ.setdefault("DW_NKD_ENABLED", "0")
    watcher = {"name": "T", "unsubscribe_token": "tok123", "id": 1}
    high_drop = {"url": "https://s.com", "source": "S", "page_summary": "",
        "products": [{"title": "Chris Reeve Sebenza 31", "url": "https://s.com/products/sebenza-31",
                      "available": True, "tags": [], "price": "650.00", "confidence": "high"}],
        "notable_items": [], "link_candidates": []}
    subject, html, text = pua.build_alert_email(watcher, ["Sebenza"], high_drop)
    assert "Better keywords mean better matches" not in html
    assert "🤔" not in html


def test_alert_no_matched_items_shows_keyword_hint():
    # Pure keyword-on-page match, nothing item-level resolved → notable/page fallback →
    # still uncertain → show the prompt.
    import os
    os.environ.setdefault("DW_NKD_ENABLED", "0")
    watcher = {"name": "T", "unsubscribe_token": "tok123", "id": 1}
    drop = {"url": "https://s.com", "source": "S", "page_summary": "some page",
        "products": [], "notable_items": ["Some context item"], "link_candidates": []}
    subject, html, text = pua.build_alert_email(watcher, ["nomatch"], drop)
    assert "Better keywords mean better matches" in html
