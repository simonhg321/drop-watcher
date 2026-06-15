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


def test_misspelled_maker_suggests_correction():
    r = maker_resolve.resolve("hindrer")
    assert r["kind"] == "typo"
    assert r["suggestion"] == "Hinderer Knives"


def test_short_garbage_does_not_fuzzy_match():
    r = maker_resolve.resolve("xq")
    assert r["kind"] == "unknown"
    assert r["suggestion"] is None
