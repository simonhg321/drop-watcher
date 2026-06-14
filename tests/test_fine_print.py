"""tests/test_fine_print.py — screened-not-endorsed fine print on outbound emails."""

import per_user_alerter
import backfill_alerter


def test_disclaimer_constants_exist():
    assert "not endorsements" in per_user_alerter.DISCLAIMER_TEXT
    assert "not endorsements" in per_user_alerter.DISCLAIMER_HTML


def test_alert_email_contains_disclaimer():
    html, text = per_user_alerter._render_alert_for_test()
    assert "not endorsements or guarantees" in html
    assert "not endorsements or guarantees" in text


def test_backfill_digest_contains_disclaimer():
    """build_backfill_digest renders the same DISCLAIMER_HTML/DISCLAIMER_TEXT (imported
    from per_user_alerter) in its HTML and text bodies."""
    shown = []   # zero-row digest — footer still appears
    _subj, html, text = backfill_alerter.build_backfill_digest(
        name="Tester",
        shown=shown,
        unsub_token="tok_test_bf_abc",
    )
    assert "not endorsements or guarantees" in html
    assert "not endorsements or guarantees" in text
