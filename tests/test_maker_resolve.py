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
    # "damascus" is a notable_model for several makers (CRK, Strider, Arno Bernard)
    # and is NOT an alias, so it genuinely reaches the ambiguous branch.
    r = maker_resolve.resolve("damascus")
    assert r["kind"] == "ambiguous"
    assert r["canonical"] is None
    assert r["suggestion"] is None


def test_none_and_blankish_inputs_are_unknown_and_never_raise():
    for bad in (None, "   ", "---", "!!!"):
        r = maker_resolve.resolve(bad)
        assert r == {"canonical": None, "suggestion": None, "kind": "unknown"}

def test_exact_match_is_case_insensitive():
    r = maker_resolve.resolve("CHRIS REEVE KNIVES")
    assert r["canonical"] == "Chris Reeve Knives"
    assert r["kind"] == "exact"

def test_missing_makers_file_returns_unknown_not_raise():
    r = maker_resolve.resolve("crk", makers_file="/nonexistent/makers.yaml")
    assert r["kind"] == "unknown"


def test_first_maker_in_adopts_first_alias_in_list():
    r = maker_resolve.first_maker_in("damascus, crk, magnacut")
    assert r["canonical"] == "Chris Reeve Knives"
    assert r["kind"] == "alias"

def test_first_maker_in_falls_back_to_model_suggestion():
    r = maker_resolve.first_maker_in("halftrack, magnacut")  # model, no alias hit
    assert r["kind"] == "model"
    assert r["suggestion"] == "Hinderer Knives"

def test_first_maker_in_unknown_when_no_token_resolves():
    r = maker_resolve.first_maker_in("magnacut, titanium")
    assert r["kind"] == "unknown"


def test_misspelled_maker_suggests_correction():
    r = maker_resolve.resolve("hindrer")
    assert r["kind"] == "typo"
    assert r["suggestion"] == "Hinderer Knives"


def test_short_garbage_does_not_fuzzy_match():
    r = maker_resolve.resolve("xq")
    assert r["kind"] == "unknown"
    assert r["suggestion"] is None
