"""record_match.py — translate a watcher into a field-scoped FTS5 query over the
source's in-stock product records. Maker-carrying watches qualify on the typed
vendor field (kills cross-brand false positives); maker-less watches match
title/tags per-record (no store-wide bleed).

FTS5 column-filter syntax used: `vendor:(term OR term)` (colon-prefix form) and
`{title tags}: (term)` (brace multi-column form). Both are accepted by SQLite 3.37+.
"""
import record_index
from makers import expand_maker


def _fts_or(terms):
    """Build an FTS5 OR phrase list from a sequence of terms, quoting each."""
    cleaned = [t.replace('"', ' ').strip() for t in terms if t and t.strip()]
    return " OR ".join(f'"{t}"' for t in cleaned)


def _keywords(watcher):
    return [k.strip() for k in (watcher.get('keywords') or '').split(',') if k.strip()]


def query(watcher, source_url=None):
    """Return product_records rows for this source that match the watcher.

    With maker set: requires vendor to match a maker alias AND title/tags to
    match a keyword — eliminates cross-brand false positives (e.g. "strider" in
    an RMJ product title no longer fires a Strider watch).

    Without maker: keyword matched against title and tags per-record — no
    store-wide bleed (fixes the stale-blob problem).
    """
    source_url = source_url or watcher.get('url')
    kws = _keywords(watcher)
    if not kws:
        return []

    # Title + tags keyword clause using brace multi-column filter syntax
    kw_clause = "{title tags} : (" + _fts_or(kws) + ")"

    maker = (watcher.get('maker') or '').strip()
    if maker:
        maker_terms = expand_maker(maker)
        if maker_terms:
            # Vendor clause: require vendor field to match a maker alias
            vendor_clause = "vendor : (" + _fts_or(maker_terms) + ")"
            fts = f"({vendor_clause}) AND ({kw_clause})"
        else:
            # Unknown maker — fall back to keyword-only (safe degradation)
            fts = kw_clause
    else:
        fts = kw_clause

    return record_index.search_source(source_url, fts)
