# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""synonyms.py — keyword synonym expansion for watch matching.

A user's cool-list term automatically also matches its known synonyms (e.g. a
Chris Reeve "CGG" is called "Unique Graphics" at some dealers). Groups in
config/keyword_synonyms.yaml are bidirectional: any term in a group expands to the
whole group. Unknown terms expand to just themselves, so matching is never
narrowed — only broadened where a group exists. Single source of truth; mirrors
the makers.py pattern (path-keyed cache so a config-dir change in tests can't
serve stale data)."""
import os
from functools import lru_cache

import paths
from config_load import load_yaml
from matching import kw_matches

_REPO_FALLBACK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'config', 'keyword_synonyms.yaml')


def _synonyms_path():
    """Deployed config wins; fall back to the in-repo copy so the feature works
    even before the file is sudo-copied into /etc/drop-watcher."""
    p = os.path.join(paths.CONFIG_DIR, 'keyword_synonyms.yaml')
    return p if os.path.exists(p) else _REPO_FALLBACK


@lru_cache(maxsize=8)
def _synonym_index(path):
    """{term(lower): (whole group, lowercased)} for every synonym group in the file."""
    index = {}
    data = load_yaml(path) or {}
    for group in data.get('groups', []) or []:
        terms = tuple(sorted({t.strip().lower() for t in (group or []) if t and t.strip()}))
        if len(terms) < 2:        # a group of one adds nothing
            continue
        for t in terms:
            index[t] = terms
    return index


def expand_keyword(kw):
    """Return [kw + any synonyms] (lowercased). Unknown → [kw-lower]; blank → []."""
    if not kw or not kw.strip():
        return []
    key = kw.strip().lower()
    try:
        grp = _synonym_index(_synonyms_path()).get(key)
    except Exception:
        grp = None
    return list(grp) if grp else [key]


def kw_matches_any(kw, text):
    """True if kw OR any of its synonyms appears in text (bounded match)."""
    return any(kw_matches(t, text) for t in expand_keyword(kw))
