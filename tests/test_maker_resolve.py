# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""Tests for maker_resolve.py — canonical maker resolution."""
import maker_resolve


def test_exact_name_resolves_canonical():
    r = maker_resolve.resolve("Chris Reeve Knives")
    assert r["canonical"] == "Chris Reeve Knives"
    assert r["kind"] == "exact"


def test_alias_resolves_to_canonical():
    r = maker_resolve.resolve("crk")
    assert r["canonical"] == "Chris Reeve Knives"
    assert r["kind"] == "alias"


def test_blank_is_unknown():
    r = maker_resolve.resolve("")
    assert r == {"canonical": None, "suggestion": None, "kind": "unknown"}


def test_model_typed_as_maker_suggests_maker():
    r = maker_resolve.resolve("halftrack")   # Hinderer notable_model
    assert r["kind"] == "model"
    assert r["suggestion"] == "Hinderer Knives"
    assert r["canonical"] is None


def test_model_shared_by_two_makers_is_ambiguous():
    r = maker_resolve.resolve("steel flame")
    assert r["kind"] in ("ambiguous", "alias", "exact")
