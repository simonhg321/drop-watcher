#!/usr/bin/env python3
"""dualrun_matcher.py — READ-ONLY blob-vs-fts5 matcher diff (cutover validation).

This is the artifact a human reads BEFORE flipping DW_MATCHER=fts5 in production.
For every recent drop x every active watcher it computes matches under BOTH the
'blob' (current prod default) and 'fts5' (candidate) matchers and reports the diff.

STRICTLY READ-ONLY. It NEVER writes the DB (no update_watcher / open_episode /
record_sent_alert), NEVER sends email or SMS, and NEVER opens an episode. It only
reads drops + watchers + the product_records index, computes in memory, and prints.

How to run it against prod
--------------------------
The cron environment already exports the DW_* vars that point at the prod DB
(DW_DB / DW_DATA_DIR). Run it the same way the alerter is invoked, e.g.:

    cd /home/shg/drop-watcher
    DW_DB=$DW_DB python3 bin/dualrun_matcher.py --minutes 1440

or simply, when the env is already loaded from the crontab/.env:

    python3 bin/dualrun_matcher.py --minutes 1440

It toggles os.environ['DW_MATCHER'] around each match call (per_user_alerter's
_matcher_mode() reads the env at call time, so no module reload is needed) and
ALWAYS restores the prior value, so importing/running this never leaves the
process in fts5 mode.

Buckets
-------
  BOTH      — blob and fts5 agree there is a match (or agree there is none).
  BLOB-ONLY — blob matches, fts5 does NOT. Flipping to fts5 would STOP this
              alert: a possible MISS. Review these first.
  FTS5-ONLY — fts5 matches, blob does NOT. Flipping to fts5 would NEWLY alert:
              either noise, or a real fix the blob matcher was missing.

It also runs a maker-alias collision check (see --validate-makers): expands each
watcher's maker and flags any alias that also appears as a literal `vendor` value
for a DIFFERENT brand in product_records — the empirical surfacing of the
expand_maker "model name == some vendor" risk.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import per_user_alerter as pua


def _match_under(mode, watcher, drop):
    """Run matches_for_watcher_drop under a given matcher mode, restoring env.

    _matcher_mode() reads os.environ at call time, so toggling per call is enough
    — no module reload. The prior DW_MATCHER value is always restored.
    """
    prev = os.environ.get('DW_MATCHER')
    os.environ['DW_MATCHER'] = mode
    try:
        return pua.matches_for_watcher_drop(watcher, drop)
    finally:
        if prev is None:
            os.environ.pop('DW_MATCHER', None)
        else:
            os.environ['DW_MATCHER'] = prev


def classify(watcher, drop):
    """Pure comparison for ONE (watcher, drop): run both matchers and bucket.

    Returns (bucket, blob_hits, fts5_hits) where bucket is one of:
      'both'      — both matched (non-empty) OR both empty (agreement)
      'blob_only' — blob matched, fts5 did not
      'fts5_only' — fts5 matched, blob did not
      'neither'   — neither matched (a flavor of agreement; counted separately
                    so the summary can ignore the vast no-match majority)

    No DB writes; pure read+compute. Safe to call from tests.
    """
    blob_hits = _match_under('blob', watcher, drop) or []
    fts5_hits = _match_under('fts5', watcher, drop) or []
    b, f = bool(blob_hits), bool(fts5_hits)
    if b and f:
        bucket = 'both'
    elif b and not f:
        bucket = 'blob_only'
    elif f and not b:
        bucket = 'fts5_only'
    else:
        bucket = 'neither'
    return bucket, blob_hits, fts5_hits


def _w_label(w):
    url = w.get('url') or '(global)'
    return (f"watcher#{w.get('id', '?')} url={url} "
            f"kw={w.get('keywords', '')!r} maker={w.get('maker', '')!r} "
            f"email={w.get('email', '?')}")


def _drop_label(d):
    return f"{d.get('source', '?')} :: {d.get('url', '?')}"


def run_diff(minutes):
    drops = db.get_recent_drops(minutes=minutes)
    watchers = db.get_active_watchers()
    print(f"== dualrun_matcher (READ-ONLY) — blob vs fts5 ==")
    print(f"window: last {minutes} min  |  drops: {len(drops)}  |  "
          f"active watchers: {len(watchers)}\n")

    buckets = {'both': [], 'blob_only': [], 'fts5_only': [], 'neither': 0}
    for w in watchers:
        for d in drops:
            bucket, blob_hits, fts5_hits = classify(w, d)
            if bucket == 'neither':
                buckets['neither'] += 1
                continue
            buckets[bucket].append((w, d, blob_hits, fts5_hits))

    def _dump(title, rows):
        print(f"\n----- {title} ({len(rows)}) -----")
        for w, d, blob_hits, fts5_hits in rows:
            print(f"  {_w_label(w)}")
            print(f"    drop:  {_drop_label(d)}")
            print(f"    blob:  {blob_hits}")
            print(f"    fts5:  {fts5_hits}")

    _dump("BLOB-ONLY  (fts5 would STOP alerting — possible miss)",
          buckets['blob_only'])
    _dump("FTS5-ONLY  (fts5 would NEWLY alert — noise or a real fix)",
          buckets['fts5_only'])
    _dump("BOTH-AGREE (both matched)", buckets['both'])

    print("\n== SUMMARY ==")
    print(f"  BOTH-agree : {len(buckets['both'])}")
    print(f"  BLOB-ONLY  : {len(buckets['blob_only'])}  (review: possible misses)")
    print(f"  FTS5-ONLY  : {len(buckets['fts5_only'])}  (review: noise vs fix)")
    print(f"  neither    : {buckets['neither']}  (no-match pairs, ignored)")


def _distinct_vendors():
    """All distinct vendor literals in the live product_records index (lowercased)."""
    try:
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT vendor FROM product_records"
            ).fetchall()
    except Exception as e:
        print(f"  (could not read product_records: {e})")
        return {}
    out = {}
    for r in rows:
        v = (r['vendor'] or '').strip()
        if v:
            out[v.lower()] = v
    return out


def validate_makers():
    """Flag maker aliases that collide with a vendor literal for a DIFFERENT brand.

    For each active watcher with a maker, expand the maker and check whether any
    expansion term ALSO exists as a `vendor` value in product_records. A model-ish
    alias (e.g. 'tanto', 'smf') that is also a vendor name would let the fts5 vendor
    clause match the wrong brand. We only warn when the colliding vendor differs
    from the watcher's own maker (same-brand vendor==alias is expected/benign).
    """
    print("\n== MAKER-ALIAS COLLISION CHECK ==")
    vendors = _distinct_vendors()
    if not vendors:
        print("  no product_records vendors found (empty index?) — nothing to check")
        return
    print(f"  distinct vendors in index: {len(vendors)}")

    watchers = db.get_active_watchers()
    seen_pairs = set()
    collisions = 0
    for w in watchers:
        maker = (w.get('maker') or '').strip()
        if not maker:
            continue
        maker_lc = maker.lower()
        # All aliases for THIS maker — a colliding vendor that is one of our own
        # aliases (e.g. maker "Chris Reeve" -> vendor "Chris Reeve Knives") is the
        # same brand and benign; only flag a vendor that is NOT a known alias of us.
        own = {a.strip().lower() for a in pua.expand_maker(maker) if a and a.strip()}
        own.add(maker_lc)
        for term in pua.expand_maker(maker):
            t = (term or '').strip().lower()
            if not t or t not in vendors:
                continue
            vendor_literal = vendors[t]
            vl = vendor_literal.lower()
            # Same-brand collision (vendor IS one of our own aliases) is expected.
            if vl in own or maker_lc in vl or vl in maker_lc:
                continue
            pair = (maker_lc, t, vendor_literal.lower())
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            collisions += 1
            print(f"  WARNING: maker {maker!r} expands to alias {term!r} which is "
                  f"ALSO a vendor literal {vendor_literal!r} (different brand) — "
                  f"fts5 vendor clause could match the wrong brand")
    if not collisions:
        print("  no maker-alias / vendor collisions detected")


def main():
    ap = argparse.ArgumentParser(
        description="READ-ONLY blob-vs-fts5 matcher diff for cutover validation.")
    ap.add_argument('--minutes', type=int, default=1440,
                    help="recent-drops window in minutes (default 1440 = 24h)")
    ap.add_argument('--validate-makers', action='store_true',
                    help="only run the maker-alias collision check, skip the diff")
    args = ap.parse_args()

    if args.validate_makers:
        validate_makers()
        return 0

    run_diff(args.minutes)
    validate_makers()
    return 0


if __name__ == '__main__':
    sys.exit(main())
