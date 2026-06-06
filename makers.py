# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""makers.py — maker->aliases expansion from config/makers.yaml.

Single source of truth for turning a user-entered maker ("Chris Reeve", "crk")
into the set of match terms (name + all aliases, lowercased). Unknown makers fall
back to the literal string so a global watch still works for any brand."""
from functools import lru_cache

import paths
from config_load import load_yaml


@lru_cache(maxsize=8)
def _maker_index(makers_file):
    """{alias_or_name(lower): [name+aliases lowercased]} for every maker in the file.
    Cached per path so a config-dir change (e.g. tests) doesn't serve stale data.
    Cron jobs are fresh processes; if this ever runs in a long-lived daemon and
    makers.yaml is edited, call _maker_index.cache_clear()."""
    index = {}
    data = load_yaml(makers_file) or {}
    for m in data.get('makers', []) or []:
        if not isinstance(m, dict):
            continue
        # str()-coerce: a YAML alias like 229 or 0044 parses as int — one bad value
        # must never crash the whole index (which silently breaks ALL maker matching).
        name = str(m.get('name') or '').strip()
        aliases = [str(a).strip() for a in (m.get('aliases') or []) if str(a).strip()]
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
        hit = _maker_index(paths.MAKERS_YAML).get(key)
    except Exception:
        hit = None
    return list(hit) if hit else [key]
