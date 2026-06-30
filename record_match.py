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


def _vendor_matches_maker(vendor, maker_terms):
    """True if vendor is blank (no signal — can't disprove the maker, so don't
    penalize) or vendor contains one of the maker's terms."""
    v = (vendor or '').strip().lower()
    if not v:
        return True
    return any(t in v for t in maker_terms)


def query(watcher, source_url=None):
    """Return product_records rows for this source that match the watcher.

    With maker set: title/tags must match a keyword, AND if the record HAS a
    vendor value it must match a maker alias — eliminates cross-brand false
    positives (e.g. "strider" in an RMJ product title no longer fires a Strider
    watch). Records with no vendor data at all (tier-3 card extraction often
    can't infer one) aren't penalized — there's no vendor signal to fail against,
    same fallback blob matching takes when there's no product line to bind to.

    Without maker: keyword matched against title and tags per-record — no
    store-wide bleed (fixes the stale-blob problem).
    """
    source_url = source_url or watcher.get('url')
    kws = _keywords(watcher)
    if not kws:
        return []

    # Title + tags keyword clause using brace multi-column filter syntax
    kw_clause = "{title tags} : (" + _fts_or(kws) + ")"
    recs = record_index.search_source(source_url, kw_clause)

    maker = (watcher.get('maker') or '').strip()
    if not maker:
        return recs
    maker_terms = expand_maker(maker)
    if not maker_terms:
        # Unknown maker — fall back to keyword-only (safe degradation)
        return recs
    return [r for r in recs if _vendor_matches_maker(r.get('vendor'), maker_terms)]
