#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""backfill_keywords.py — one-time keyword sanity pass over existing ACTIVE watches
(S71 keyword sanitizer). Dry-run by default; --apply writes.

  python3 bin/backfill_keywords.py            # print before/after table, change nothing
  python3 bin/backfill_keywords.py --apply    # write corrections, preserve keywords_raw
  python3 bin/backfill_keywords.py --ai       # also ask Haiku about junk lists (works with either)

keywords_raw is set from the pre-correction value and only if not already set —
rollback for any watch is: copy keywords_raw back into keywords.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db
import keyword_sanitizer
from watcher_signup import _keyword_too_generic  # noqa: E402


def _ai_rescue(keywords, maker):
    from watcher_signup import correct_keywords_ai
    return correct_keywords_ai(keywords, maker)


def backfill(apply=False, use_ai=False):
    """Sanitize every active watch. Returns the list of would-be/applied changes:
    [{id, email, before, keywords, maker_before, maker, via}]."""
    changes = []
    with db.get_db() as conn:
        watchers = [dict(r) for r in conn.execute(
            "SELECT * FROM watchers WHERE active=1").fetchall()]

    for w in watchers:
        before = w.get('keywords') or ''
        maker_before = w.get('maker') or ''
        san = keyword_sanitizer.sanitize(before, maker=maker_before)
        keywords, maker, via = san['keywords'], san['maker'], 'rules'

        if use_ai and (san['notes'] == 'all_dropped' or _keyword_too_generic(keywords)):
            ai_kws = _ai_rescue(before, maker)
            fixed = keyword_sanitizer.apply_ai_correction(san, ai_kws) if ai_kws else None
            if fixed:
                keywords, via = fixed, 'ai'

        if keywords == before and maker == maker_before:
            continue

        changes.append({'id': w['id'], 'email': w['email'], 'before': before,
                        'keywords': keywords, 'maker_before': maker_before,
                        'maker': maker, 'via': via})
        if apply:
            fields = {'keywords': keywords}
            if maker != maker_before:
                fields['maker'] = maker
            if not (w.get('keywords_raw') or '').strip():
                fields['keywords_raw'] = before
            db.update_watcher(w['id'], **fields)

    return changes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='write changes (default: dry-run)')
    ap.add_argument('--ai', action='store_true', help='Haiku rescue for junk keyword lists')
    args = ap.parse_args()

    changes = backfill(apply=args.apply, use_ai=args.ai)
    mode = 'APPLIED' if args.apply else 'DRY-RUN'
    print(f"{mode}: {len(changes)} watch(es) corrected\n")
    for c in changes:
        print(f"[{c['id']}] {c['email']}  ({c['via']})")
        print(f"    keywords: {c['before']!r} -> {c['keywords']!r}")
        if c['maker'] != c['maker_before']:
            print(f"    maker:    {c['maker_before']!r} -> {c['maker']!r}")
    if not args.apply and changes:
        print("\nRe-run with --apply to write.")


if __name__ == '__main__':
    main()
