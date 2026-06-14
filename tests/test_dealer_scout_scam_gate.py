"""Behavioral tests for the scam-gate in dealer_scout._promote_one.

Three contracts:
  1. A flagged candidate is blocked, rejected in DB, operator notified, never written.
  2. A clean candidate passes through and is appended to sources.yaml.
  3. operator --approve (override=True) bypasses the gate even for quarantined domains.
"""
import dealer_scout
from scam_source_filter import Verdict


def _patch_curated_empty(monkeypatch):
    """Neutralize the 'already curated' short-circuit so tests reach the scam gate."""
    monkeypatch.setattr(dealer_scout, "curated_domains", lambda: set())


def test_promote_one_blocks_flagged_candidate(monkeypatch):
    cand = {"domain": "scammy.com", "category": "knife", "sample_url": "https://scammy.com",
            "confidence": 0.90, "brands": ""}
    _patch_curated_empty(monkeypatch)
    monkeypatch.setattr(dealer_scout.scam_gate, "evaluate",
                        lambda *a, **k: Verdict(action="quarantine", score=9, reasons=["uniform discount"]))
    appended = []
    monkeypatch.setattr(dealer_scout, "_append_dealer_to_sources", lambda c: appended.append(c) or True)
    statuses = []
    monkeypatch.setattr(dealer_scout.db, "set_dealer_candidate_status",
                        lambda d, s: statuses.append((d, s)))
    notified = []
    monkeypatch.setattr(dealer_scout.scam_gate, "notify_operator",
                        lambda *a, **k: notified.append(a[0]))

    ok = dealer_scout._promote_one(cand)

    assert ok is False
    assert appended == []                            # never written to sources.yaml
    assert ("scammy.com", "rejected") in statuses
    assert "scammy.com" in notified


def test_promote_one_allows_clean_candidate(monkeypatch):
    cand = {"domain": "legit.com", "category": "knife", "sample_url": "https://legit.com",
            "confidence": 0.92, "brands": ""}
    _patch_curated_empty(monkeypatch)
    monkeypatch.setattr(dealer_scout.scam_gate, "evaluate",
                        lambda *a, **k: Verdict(action="ingest", score=0, reasons=[]))
    appended = []
    monkeypatch.setattr(dealer_scout, "_append_dealer_to_sources", lambda c: appended.append(c) or True)
    monkeypatch.setattr(dealer_scout.db, "set_dealer_candidate_status", lambda d, s: None)
    monkeypatch.setattr(dealer_scout.db, "mark_dealer_candidate_notified", lambda d: None)
    monkeypatch.setattr(dealer_scout, "send_dealer_alert", lambda c: None)

    ok = dealer_scout._promote_one(cand)

    assert ok is True
    assert appended == [cand]                        # added as normal


def test_promote_one_blocks_review_verdict(monkeypatch):
    # A borderline 'review' verdict is also blocked (operator can --approve to override).
    cand = {"domain": "borderline.com", "category": "knife", "sample_url": "https://borderline.com"}
    _patch_curated_empty(monkeypatch)
    monkeypatch.setattr(dealer_scout.scam_gate, "evaluate",
                        lambda *a, **k: Verdict(action="review", score=3, reasons=["uniform discount"]))
    appended = []
    monkeypatch.setattr(dealer_scout, "_append_dealer_to_sources", lambda c: appended.append(c) or True)
    statuses = []
    monkeypatch.setattr(dealer_scout.db, "set_dealer_candidate_status",
                        lambda d, s: statuses.append((d, s)))
    notified = []
    monkeypatch.setattr(dealer_scout.scam_gate, "notify_operator",
                        lambda *a, **k: notified.append(a[0]))

    ok = dealer_scout._promote_one(cand)

    assert ok is False
    assert appended == []
    assert ("borderline.com", "rejected") in statuses
    assert "borderline.com" in notified


def test_promote_one_override_bypasses_gate(monkeypatch):
    cand = {"domain": "flagged-but-approved.com", "category": "knife",
            "sample_url": "https://flagged-but-approved.com",
            "confidence": 0.85, "brands": ""}
    _patch_curated_empty(monkeypatch)
    monkeypatch.setattr(dealer_scout.scam_gate, "evaluate",
                        lambda *a, **k: Verdict(action="quarantine", score=9, reasons=["x"]))
    appended = []
    monkeypatch.setattr(dealer_scout, "_append_dealer_to_sources", lambda c: appended.append(c) or True)
    monkeypatch.setattr(dealer_scout.db, "set_dealer_candidate_status", lambda d, s: None)
    monkeypatch.setattr(dealer_scout.db, "mark_dealer_candidate_notified", lambda d: None)
    monkeypatch.setattr(dealer_scout, "send_dealer_alert", lambda c: None)

    ok = dealer_scout._promote_one(cand, override=True)

    assert ok is True
    assert appended == [cand]                        # human override wins
