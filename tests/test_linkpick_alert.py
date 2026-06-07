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
