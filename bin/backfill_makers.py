#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""CLI entry point for backfill_makers — infer makers for existing maker-less watches.

Usage:
  bin/backfill_makers.py          # dry-run (no writes)
  bin/backfill_makers.py --apply  # write inferred makers to DB
"""
import argparse
import sys

sys.path.insert(0, __file__.rsplit('/bin/', 1)[0])  # import project modules

import db
import backfill_makers


def main():
    ap = argparse.ArgumentParser(
        description="Infer makers for existing maker-less URL watches.")
    ap.add_argument('--apply', action='store_true',
                    help='write changes (default: dry-run)')
    args = ap.parse_args()
    plan = backfill_makers.plan_backfill(db)
    print(f"infer-and-set: {len(plan['set'])}   needs-email: {len(plan['email'])}")
    for wid, name in plan['set'].items():
        print(f"  SET {wid} -> {name}")
    for w in plan['email']:
        print(f"  EMAIL {w['id']} ({w.get('email')}) kw={w.get('keywords')!r}")
    if args.apply:
        print(f"applied: {backfill_makers.apply_backfill(db, plan)} makers set")
    else:
        print("dry-run — no writes. Re-run with --apply to commit.")


if __name__ == '__main__':
    main()
