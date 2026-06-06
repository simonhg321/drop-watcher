# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""makers.py — maker->aliases expansion from config/makers.yaml.

Single source of truth for turning a user-entered maker ("Chris Reeve", "crk")
into the set of match terms (name + all aliases, lowercased). Unknown makers fall
back to the literal string so a global watch still works for any brand."""
import os
from functools import lru_cache

import paths
from config_load import load_yaml

MAKERS_FILE = os.path.join(paths.CONFIG_DIR, 'makers.yaml')


@lru_cache(maxsize=1)
def _maker_index():
    """{alias_or_name(lower): [name+aliases lowercased]} for every maker."""
    index = {}
    data = load_yaml(MAKERS_FILE) or {}
    for m in data.get('makers', []) or []:
        name = (m.get('name') or '').strip()
        aliases = [a.strip() for a in (m.get('aliases') or []) if a and a.strip()]
        terms = [t.lower() for t in ([name] + aliases) if t]
        if not terms:
            continue
        for key in terms:
            index[key] = terms
    return index


def expand_maker(maker):
    """Return match terms for a maker. Known -> name+aliases (lowercased); unknown ->
    [literal lowercased]; blank -> []. Never raises."""
    if not maker or not maker.strip():
        return []
    key = maker.strip().lower()
    try:
        hit = _maker_index().get(key)
    except Exception:
        hit = None
    return list(hit) if hit else [key]
