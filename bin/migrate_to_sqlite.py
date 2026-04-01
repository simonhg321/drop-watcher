#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
migrate_to_sqlite.py — One-time migration from JSON/JSONL files to SQLite.
Reads all state files, inserts into dropwatcher.db, keeps .bak copies.

Usage:
  python3 bin/migrate_to_sqlite.py          # dry run — shows counts
  python3 bin/migrate_to_sqlite.py --apply  # actually migrate

HGR
"""

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import paths
import db


def load_jsonl(path):
    """Load a JSONL file, return list of dicts."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def load_json(path):
    """Load a JSON file, return parsed data."""
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return None


def backup(path):
    """Create .bak copy of a file."""
    if os.path.exists(path):
        bak = path + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
            print(f"  backed up: {bak}")


def migrate_watchers(dry_run=True):
    data = load_json(paths.WATCHERS_JSON)
    if not data:
        print("  watchers.json: not found or empty")
        return 0
    print(f"  watchers.json: {len(data)} entries")
    if dry_run:
        return len(data)
    backup(paths.WATCHERS_JSON)
    with db.get_db() as conn:
        for w in data:
            conn.execute("""
                INSERT OR IGNORE INTO watchers
                (id, email, url, keywords, name, priority, phone, sms_approved,
                 sms_verify_code, sms_verify_expires, active, verify_token,
                 unsubscribe_token, created, last_alert, alert_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                w.get('id', ''),
                w.get('email', ''),
                w.get('url', ''),
                w.get('keywords', ''),
                w.get('name', ''),
                w.get('priority', 'high'),
                w.get('phone', ''),
                1 if w.get('sms_approved') else 0,
                w.get('sms_verify_code'),
                w.get('sms_verify_expires'),
                1 if w.get('active') else 0,
                w.get('verify_token'),
                w.get('unsubscribe_token', ''),
                w.get('created', ''),
                w.get('last_alert'),
                w.get('alert_count', 0),
            ))
    return len(data)


def migrate_drops(dry_run=True):
    entries = load_jsonl(paths.DROPS_JSONL)
    print(f"  drops.jsonl: {len(entries)} entries")
    if dry_run:
        return len(entries)
    backup(paths.DROPS_JSONL)
    with db.get_db() as conn:
        for d in entries:
            conn.execute("""
                INSERT INTO drops (source, url, timestamp, priority, page_summary, notable_items, raw_json)
                VALUES (?,?,?,?,?,?,?)
            """, (
                d.get('source', ''),
                d.get('url', ''),
                d.get('timestamp', ''),
                d.get('priority', 'medium'),
                d.get('page_summary', ''),
                json.dumps(d.get('notable_items', [])),
                json.dumps(d),
            ))
    return len(entries)


def migrate_alerts_sent(dry_run=True):
    entries = load_jsonl(paths.ALERTS_SENT_JSONL)
    print(f"  alerts_sent.jsonl: {len(entries)} entries")
    if dry_run:
        return len(entries)
    backup(paths.ALERTS_SENT_JSONL)
    with db.get_db() as conn:
        for e in entries:
            conn.execute("""
                INSERT INTO alert_tracking (alert_type, alert_key, recipient, sent_at)
                VALUES (?,?,?,?)
            """, ('email', e.get('alert_id', ''), '', e.get('sent_at', '')))
    return len(entries)


def migrate_sms_sent(dry_run=True):
    entries = load_jsonl(paths.SMS_SENT_JSONL)
    print(f"  sms_sent.jsonl: {len(entries)} entries")
    if dry_run:
        return len(entries)
    backup(paths.SMS_SENT_JSONL)
    with db.get_db() as conn:
        for e in entries:
            conn.execute("""
                INSERT INTO alert_tracking (alert_type, alert_key, phone, sent_at)
                VALUES (?,?,?,?)
            """, ('sms', e.get('alert_id', ''), e.get('phone', ''), e.get('sent_at', '')))
    return len(entries)


def migrate_per_user_sent(dry_run=True):
    data = load_json(os.path.join(paths.DATA_DIR, 'per_user_sent.json'))
    if not data:
        print("  per_user_sent.json: not found or empty")
        return 0
    print(f"  per_user_sent.json: {len(data)} entries")
    if dry_run:
        return len(data)
    backup(os.path.join(paths.DATA_DIR, 'per_user_sent.json'))
    with db.get_db() as conn:
        for key, ts in data.items():
            conn.execute("""
                INSERT INTO alert_tracking (alert_type, alert_key, sent_at)
                VALUES (?,?,?)
            """, ('per_user', key, ts))
    return len(data)


def migrate_api_usage(dry_run=True):
    entries = load_jsonl(paths.API_USAGE_JSONL)
    print(f"  api_usage.jsonl: {len(entries)} entries")
    if dry_run:
        return len(entries)
    backup(paths.API_USAGE_JSONL)
    with db.get_db() as conn:
        for e in entries:
            conn.execute("""
                INSERT INTO api_usage (ts, caller, site, model, input_tokens, output_tokens)
                VALUES (?,?,?,?,?,?)
            """, (
                e.get('ts', ''),
                e.get('caller', ''),
                e.get('site', ''),
                e.get('model', ''),
                e.get('input_tokens', 0),
                e.get('output_tokens', 0),
            ))
    return len(entries)


def migrate_ai_calls(dry_run=True):
    entries = load_jsonl(paths.AI_CALLS_JSONL)
    print(f"  ai_calls.jsonl: {len(entries)} entries")
    if dry_run:
        return len(entries)
    backup(paths.AI_CALLS_JSONL)
    with db.get_db() as conn:
        for e in entries:
            conn.execute("""
                INSERT INTO ai_calls (ts, caller, site, url, prompt_snippet, response)
                VALUES (?,?,?,?,?,?)
            """, (
                e.get('ts', ''),
                e.get('caller', ''),
                e.get('site', ''),
                e.get('url', ''),
                e.get('prompt_snippet', '')[:1000],
                json.dumps(e.get('response', '')),
            ))
    return len(entries)


def migrate_seen_content(dry_run=True):
    data = load_json(paths.SEEN_CONTENT_JSON)
    if not data:
        print("  seen_content.json: not found or empty")
        return 0
    print(f"  seen_content.json: {len(data)} entries")
    if dry_run:
        return len(data)
    backup(paths.SEEN_CONTENT_JSON)
    with db.get_db() as conn:
        for key, ts in data.items():
            conn.execute(
                "INSERT OR IGNORE INTO seen_content (content_key, seen_at) VALUES (?,?)",
                (key, ts)
            )
    return len(data)


def migrate_seen_items(dry_run=True):
    data = load_json(paths.SEEN_ITEMS_JSON)
    if not data:
        print("  seen_items.json: not found or empty")
        return 0
    print(f"  seen_items.json: {len(data)} entries")
    if dry_run:
        return len(data)
    backup(paths.SEEN_ITEMS_JSON)
    with db.get_db() as conn:
        for key, ts in data.items():
            conn.execute(
                "INSERT OR IGNORE INTO seen_items (item_key, seen_at) VALUES (?,?)",
                (key, ts)
            )
    return len(data)


def migrate_seen_feeds(dry_run=True):
    data = load_json(paths.SEEN_FEEDS_JSON)
    if not data:
        print("  seen_feeds.json: not found or empty")
        return 0
    print(f"  seen_feeds.json: {len(data)} entries")
    if dry_run:
        return len(data)
    backup(paths.SEEN_FEEDS_JSON)
    with db.get_db() as conn:
        for key, ts in data.items():
            conn.execute(
                "INSERT OR IGNORE INTO seen_feeds (feed_key, seen_at) VALUES (?,?)",
                (key, ts)
            )
    return len(data)


def migrate_discord_sent(dry_run=True):
    data = load_json(os.path.join(paths.DATA_DIR, 'discord_sent.json'))
    if not data:
        print("  discord_sent.json: not found or empty")
        return 0
    print(f"  discord_sent.json: {len(data)} entries")
    if dry_run:
        return len(data)
    backup(os.path.join(paths.DATA_DIR, 'discord_sent.json'))
    with db.get_db() as conn:
        for did, ts in data.items():
            conn.execute(
                "INSERT OR IGNORE INTO discord_sent (drop_id, sent_at) VALUES (?,?)",
                (did, ts)
            )
    return len(data)


def migrate_pageviews(dry_run=True):
    entries = load_jsonl(paths.PAGEVIEWS_JSONL)
    print(f"  pageviews.jsonl: {len(entries)} entries")
    if dry_run:
        return len(entries)
    backup(paths.PAGEVIEWS_JSONL)
    with db.get_db() as conn:
        for e in entries:
            conn.execute("""
                INSERT INTO pageviews (vid, path, ref, ip, ts)
                VALUES (?,?,?,?,?)
            """, (
                e.get('vid', ''),
                e.get('path', ''),
                e.get('ref', ''),
                e.get('ip', ''),
                e.get('ts', ''),
            ))
    return len(entries)


def main():
    dry_run = '--apply' not in sys.argv

    if dry_run:
        print("=== DRY RUN === (pass --apply to migrate)\n")
    else:
        print("=== MIGRATING ===\n")

    total = 0
    print("Migrating state files to SQLite...")
    total += migrate_watchers(dry_run)
    total += migrate_drops(dry_run)
    total += migrate_alerts_sent(dry_run)
    total += migrate_sms_sent(dry_run)
    total += migrate_per_user_sent(dry_run)
    total += migrate_api_usage(dry_run)
    total += migrate_ai_calls(dry_run)
    total += migrate_seen_content(dry_run)
    total += migrate_seen_items(dry_run)
    total += migrate_seen_feeds(dry_run)
    total += migrate_discord_sent(dry_run)
    total += migrate_pageviews(dry_run)

    print(f"\nTotal: {total} records")
    if dry_run:
        print("\nRun with --apply to perform the migration.")
        print(f"Database will be created at: {db.DB_PATH}")
    else:
        print(f"\nDatabase created at: {db.DB_PATH}")
        print("Original files backed up with .bak extension.")
        print("Monitor for 24h before removing .bak files.")


if __name__ == '__main__':
    main()
