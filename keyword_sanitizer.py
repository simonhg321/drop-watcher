# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""keyword_sanitizer.py — silent sanity pass over user-typed watch keywords
(Simon 2026-07-17). Deterministic fixes for the failure classes we've seen in
prod; judgment calls are left to the AI pass at signup. Pure and never raises —
worst case the input comes back unchanged. Spec:
docs/superpowers/specs/2026-07-17-keyword-sanitizer-design.md
"""
import logging
import re

import maker_resolve

log = logging.getLogger(__name__)

# Storefront/condition phrases users type instead of a product. Keywords match
# listing text, where button text never appears — such a watch can never fire
# usefully. Phrase-level (the whole keyword equals one of these), deliberately
# narrower than watcher_signup._GENERIC_KNIFE_TOKENS (token-level).
STOREFRONT_KEYWORDS = {
    'in stock', 'in-stock', 'instock', 'back in stock', 'restock', 'restocked',
    'add to cart', 'buy it now', 'buy now', 'buy',
    'sale', 'discount', 'clearance', 'available', 'new', 'drop', 'drops',
}

_WS = re.compile(r'\s+')


def _split_items(keywords_str):
    return [i for i in (_WS.sub(' ', p).strip() for p in (keywords_str or '').split(','))
            if i]


def _same_maker_split(item):
    """If every token of a multi-word item resolves (alias/model) to the SAME
    canonical maker, return (tokens, canonical) — else (None, None)."""
    tokens = item.split(' ')
    if len(tokens) < 2:
        return None, None
    canonicals = set()
    for t in tokens:
        r = maker_resolve.resolve(t)
        name = r.get('canonical') or r.get('suggestion')
        if not name:
            return None, None
        canonicals.add(name)
    if len(canonicals) != 1:
        return None, None
    return tokens, canonicals.pop()


def apply_ai_correction(det_result, ai_keywords):
    """Validate an AI-suggested keyword list against the deterministic rules.
    Returns the corrected comma-joined string, or None to keep det_result as-is.
    The AI never gets to make things worse: empty, oversized, or still-junk
    suggestions are rejected wholesale."""
    try:
        if not ai_keywords or not isinstance(ai_keywords, list) or len(ai_keywords) > 8:
            return None
        cleaned = []
        for k in ai_keywords:
            k = _WS.sub(' ', str(k)).strip()
            if len(k) <= 1 or len(k) > 60 or k.lower() in STOREFRONT_KEYWORDS:
                return None
            cleaned.append(k)
        corrected = ', '.join(cleaned)
        return corrected if corrected != det_result.get('keywords') else None
    except Exception as e:
        log.error(f"apply_ai_correction failed, ignoring AI suggestion: {e}")
        return None


def sanitize(keywords_str, maker=''):
    """Deterministic keyword sanity pass. Returns dict:
      keywords: corrected comma-joined string
      maker:    canonical maker if extracted into an empty maker field, else input
      changed:  True when keywords differ from input
      dropped:  items removed (junk classes)
      notes:    '' | 'all_dropped' (everything was junk — original kept, AI pass
                should look at it; a watch is never emptied here)
    Never raises."""
    original = keywords_str or ''
    out_maker = maker or ''
    try:
        items = _split_items(original)
        kept, dropped = [], []
        seen = set()
        extracted_maker = ''

        for item in items:
            low = item.lower()
            if len(item) <= 1:
                dropped.append(item)
                continue
            if low in STOREFRONT_KEYWORDS:
                dropped.append(item)
                continue
            tokens, canonical = _same_maker_split(item)
            parts = tokens if tokens else [item]
            if tokens and not extracted_maker:
                extracted_maker = canonical
            for p in parts:
                if p.lower() not in seen:
                    seen.add(p.lower())
                    kept.append(p)

        if not kept:
            return {'keywords': original, 'maker': out_maker, 'changed': False,
                    'dropped': [], 'notes': 'all_dropped' if items else ''}

        if extracted_maker and not out_maker.strip():
            out_maker = extracted_maker

        corrected = ', '.join(kept)
        return {'keywords': corrected, 'maker': out_maker,
                'changed': corrected != original, 'dropped': dropped, 'notes': ''}
    except Exception as e:
        log.error(f"keyword sanitize failed for {original[:80]!r}, passing through: {e}")
        return {'keywords': original, 'maker': out_maker, 'changed': False,
                'dropped': [], 'notes': ''}
