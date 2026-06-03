"""Keyword matching primitive — single source of truth.

Shared by per_user_alerter (alert send path) and watcher_signup (signup check +
dashboard render) so the two never diverge on what counts as a match. Keep this
module side-effect free so the Flask app can import it cheaply.
"""
import re


def kw_matches(kw, text):
    """Substring match, bounded so a word-like keyword doesn't fire inside a
    larger word ('axe' must not match 'relaxed', 'tin' not 'continental').

    Keywords with alphanumeric edges get non-alphanumeric boundary anchoring;
    keywords with punctuation edges (HTML snippets, quoted phrases) keep plain
    substring semantics, since boundaries don't apply meaningfully to them.
    Both kw and text are expected lowercased.
    """
    if not kw:
        return False
    if kw[0].isalnum() and kw[-1].isalnum():
        return re.search(r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])', text) is not None
    return kw in text
