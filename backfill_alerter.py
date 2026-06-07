# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
backfill_alerter.py — One-time "what's already in stock" matcher for new watchers.

The live per_user_alerter only looks at drops from the last DROPS_WINDOW_MINUTES, so a
brand-new watcher hears nothing until a matching drop happens to land *after* they
activate. This module matches a freshly-activated watcher (or a batch of silent ones)
against the last N days of drops and sends ONE digest of what is already live — using the
exact same matching decision (matches_for_watcher_drop) as the live alerter, so the two
can never diverge on what counts as a match.

Call paths:
  - backfill_for_email(email)   — hooked into the verify/activation flow in watcher_signup
  - CLI:  python3 backfill_alerter.py [--emails a,b | --today | --silent-only]
                                      [--days 7] [--dry-run] [--include-tests]
HGR
"""

import argparse
import html as html_mod
import logging
import re
from datetime import datetime, timezone

import db
from matching import kw_matches
from per_user_alerter import (
    matches_for_watcher_drop,
    cooldown_key,
    select_matched_products,
    MATCHED_PRODUCTS_CAP,
    disclaimer_html,
    DISCLAIMER_TEXT,
    COOLDOWN_HOURS,
)
from alerter import send_email

LOOKBACK_DAYS = 7
MAX_DROPS_PER_DIGEST = 8

# Self / test addresses excluded from batch runs by default (Simon's own signups).
TEST_ADDRESSES = {
    'simon@instockornot.club', 'simon@instickornot.club',
    'info@instockornot.club', 'simonhg@gmail.com',
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [backfill_alerter] %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)


def _drop_key(drop):
    """Display identity for the digest: the canonical page URL. Unlike the live
    alerter (which keys on url+timestamp+items so re-scrapes stay distinct), a
    backfill is a one-time "what's in stock right now" snapshot — so the SAME
    collection page scraped many times over the lookback window should collapse to
    a single row, not flood the digest with near-identical entries."""
    return (drop.get('url') or '').lower()


def filter_test_addresses(emails, include_tests=False):
    """Drop self/test addresses from a batch selection unless explicitly included.
    Preserves order and de-dupes nothing else."""
    if include_tests:
        return list(emails)
    return [e for e in emails if e.lower() not in TEST_ADDRESSES]


def find_backfill_matches(watchers, drops):
    """Match a set of watchers (all for one email) against drops.

    Returns (shown, tuples):
      tuples — every (watcher, matches, drop, cooldown_key) that matched and is NOT
               already in cooldown (so the live alerter and a prior backfill don't
               double-send).
      shown  — deduped-by-drop list of (matches, drop), newest-first as get_recent_drops
               returns them, for rendering the digest.
    """
    tuples = []
    for w in watchers:
        for drop in drops:
            matches = matches_for_watcher_drop(w, drop)
            if not matches:
                continue
            ck = cooldown_key(w['id'], (drop.get('url') or '').lower(), matches)
            if db.is_cooldown_active(ck, hours=COOLDOWN_HOURS):
                continue
            tuples.append((w, matches, drop, ck))

    seen = set()
    shown = []
    for _w, matches, drop, _ck in tuples:
        k = _drop_key(drop)
        if k in seen:
            continue
        seen.add(k)
        shown.append((matches, drop))
    return shown, tuples


_PRICE_RE = re.compile(r'\$[\d,]+(?:\.\d{2})?')


def _split_title_price(text):
    """Notable-item lines read like 'Maker Model Steel - $312.00 (in stock)'. Pull the
    price out and trim the title to the part before the price tail."""
    m = _PRICE_RE.search(text)
    price = m.group(0).lstrip('$') if m else ''
    title = text
    if m:
        idx = text.rfind(' - ', 0, m.start())
        title = text[:idx] if idx != -1 else text[:m.start()]
    return title.strip(' -–—'), price


def _item_link(drop):
    """The most specific URL we can stand behind for a notable item. Reddit posts and
    feed entries ARE the listing, so use that; otherwise the actual page we scraped.
    We deliberately do NOT fabricate /search URLs — store search paths vary and a
    guessed link 404s (verified: Edgeworks works, EDC Lifestyle + Knife Art do not).
    A working page beats a dead product guess."""
    return drop.get('entry_url') or drop.get('url') or ''


def digest_items(drop, matches):
    """Resolve a drop into the specific matched items to show, each with the best
    link we can stand behind. Priority: structured product URLs → matched notable-item
    lines (name + price, linked to the post/page) → the page itself as a last resort."""
    prods = select_matched_products(drop.get('products') or [], matches)
    if prods:
        return [{'title': p.get('title') or p.get('url'),
                 'url': p.get('url'),
                 'price': p.get('price', '')} for p in prods]

    link = _item_link(drop)
    items = []
    needles = [m.lower() for m in matches if m]
    for n in (drop.get('notable_items') or []):
        nl = n.lower()
        if any(kw_matches(k, nl) for k in needles):
            title, price = _split_title_price(n)
            items.append({'title': title or n, 'url': link, 'price': price})
        if len(items) >= MATCHED_PRODUCTS_CAP:
            break
    if items:
        return items

    # Keyword matched the page excerpt, not a discrete notable item — link the page.
    return [{'title': drop.get('source', '') or link, 'url': link, 'price': ''}]


def build_backfill_digest(name, shown, unsub_token):
    """One digest email listing drops already in stock that match the watcher.
    `shown` is a list of (matches, drop). Returns (subject, html, text)."""
    safe_name = html_mod.escape(name or 'Watcher')
    n = len(shown)
    subject = f"[DROP WATCHER] {n} match{'es' if n != 1 else ''} already in stock"

    rows_html = ''
    rows_text = ''
    for matches, drop in shown:
        src = html_mod.escape(drop.get('source', ''))
        kw = '  ·  '.join(html_mod.escape(m) for m in matches)

        # Resolve to the specific matched items, each with a product-landing link.
        items = digest_items(drop, matches)
        li_html = ''.join(
            f'<li style="margin:6px 0"><a href="{html_mod.escape(it["url"])}" '
            f'style="color:#ff8c42;text-decoration:none">{html_mod.escape(it["title"])}</a>'
            f'{(" — $" + html_mod.escape(str(it["price"]))) if it.get("price") else ""}</li>'
            for it in items
        )
        items_text = '\n'.join(
            f"    • {it['title']}"
            f"{(' — $' + str(it['price'])) if it.get('price') else ''}\n      {it['url']}"
            for it in items
        )

        rows_html += f'''
      <div style="background:#161616;border:1px solid #222;padding:16px;margin:16px 0">
        <div style="color:#888;font-size:11px;text-transform:uppercase;letter-spacing:0.08em">{src} · matched: {kw}</div>
        <ul style="margin:10px 0 0;padding-left:20px;list-style:none">{li_html}</ul>
      </div>'''
        rows_text += (
            f"- {drop.get('source','')}  (matched: {', '.join(matches)})\n"
            f"{items_text}\n\n"
        )

    html = f"""
    <div style="font-family:monospace;background:#0a0a0a;color:#e8e8e8;padding:24px;max-width:600px">
      <h2 style="color:#ff2d2d;margin:0 0 16px">⚡ DROP WATCHER</h2>
      <p style="color:#aaa;margin:0 0 20px;font-size:13px">instockornot.club</p>
      <p>Hey {safe_name} — you're live. Here's what's <strong>already in stock</strong>
         matching your watch{'es' if n != 1 else ''} right now:</p>
      {rows_html}
      <p style="margin:20px 0 0">
        <a href="https://instockornot.club/my-alerts.html?token={unsub_token}"
           style="background:#e67e22;color:#fff;padding:10px 20px;text-decoration:none;font-size:11px;letter-spacing:0.1em;text-transform:uppercase">My Alerts Dashboard</a>
      </p>
      {disclaimer_html()}
      <hr style="border:none;border-top:1px solid #222;margin:32px 0">
      <p style="color:#444;font-size:11px">
        <a href="https://instockornot.club/api/unsubscribe/{unsub_token}" style="color:#444">Unsubscribe</a> · instockornot.club
      </p>
    </div>
    """

    text = (
        f"DROP WATCHER — already in stock\n\n"
        f"Hey {name or 'Watcher'} — you're live. Here's what already matches your "
        f"watch{'es' if n != 1 else ''} right now:\n\n"
        f"{rows_text}"
        f"{DISCLAIMER_TEXT}\n"
        f"Dashboard: https://instockornot.club/my-alerts.html?token={unsub_token}\n"
        f"Unsubscribe: https://instockornot.club/api/unsubscribe/{unsub_token}"
    )
    return subject, html, text


def backfill_for_email(email, days=LOOKBACK_DAYS, dry_run=False, bcc=None):
    """Match every active watch for `email` against the last `days` of drops and send
    one digest of what is already in stock. Idempotent via per-(watcher,url,matches)
    cooldown. `bcc` is an optional list of addresses to blind-copy (ops/audit).
    Returns a summary dict; never raises on no-match (returns sent=False)."""
    email_l = email.lower()
    watchers = [w for w in db.get_active_watchers() if w['email'].lower() == email_l]
    result = {'email': email, 'matched_drops': 0, 'shown': 0, 'sent': False}
    if not watchers:
        result['reason'] = 'no active watches'
        return result

    drops = db.get_recent_drops(hours=days * 24)
    shown_all, tuples = find_backfill_matches(watchers, drops)
    result['matched_drops'] = len({_drop_key(d) for _w, _m, d, _ck in tuples})

    shown = shown_all[:MAX_DROPS_PER_DIGEST]
    result['shown'] = len(shown)
    if not shown:
        return result

    if dry_run:
        result['dry_run'] = True
        result['preview'] = [(m, d.get('source', ''), d.get('url', '')) for m, d in shown]
        return result

    name = watchers[0].get('name') or 'Watcher'
    unsub = watchers[0]['unsubscribe_token']
    subject, html, text = build_backfill_digest(name, shown, unsub)

    try:
        ok = send_email(subject, html, text, to_addr=email, extra_recipients=bcc or None)
    except Exception as e:
        log.error(f"backfill send failed for {email}: {e}")
        result['error'] = str(e)
        return result

    if not ok:
        result['error'] = 'send_failed'
        return result

    result['sent'] = True
    now = datetime.now(timezone.utc).isoformat()
    shown_keys = {_drop_key(d) for _m, d in shown}
    bumped = {}
    for w, _matches, drop, ck in tuples:
        if _drop_key(drop) not in shown_keys:
            continue
        db.mark_cooldown(ck, recipient=email)
        bumped.setdefault(w['id'], w)
    for wid, w in bumped.items():
        db.update_watcher(
            wid,
            last_alert=now,
            alert_count=(w.get('alert_count', 0) or 0) + 1,
        )
    log.info(f"backfill sent to {email}: {len(shown)} drops shown "
             f"({result['matched_drops']} matched), {len(bumped)} watch(es) bumped")
    return result


def _select_emails(args):
    """Resolve the CLI selection flags into a de-duped, ordered list of emails."""
    today = datetime.now(timezone.utc).date().isoformat()
    active = db.get_active_watchers()

    if args.emails:
        emails = [e.strip() for e in args.emails.split(',') if e.strip()]
    elif args.today:
        emails = [w['email'] for w in active if (w.get('created') or '').startswith(today)]
    elif args.silent_only:
        emails = [w['email'] for w in active
                  if not w.get('alert_count') and not w.get('last_alert')]
    else:
        emails = []

    # De-dupe preserving order.
    seen = set()
    ordered = []
    for e in emails:
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        ordered.append(e)
    return filter_test_addresses(ordered, include_tests=args.include_tests)


def main():
    ap = argparse.ArgumentParser(description="Backfill new/silent watchers against the recent drop corpus.")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument('--emails', help='comma-separated emails to backfill')
    sel.add_argument('--today', action='store_true', help='active watchers created today')
    sel.add_argument('--silent-only', action='store_true',
                     help='active watchers that have never been alerted')
    ap.add_argument('--days', type=int, default=LOOKBACK_DAYS, help=f'lookback days (default {LOOKBACK_DAYS})')
    ap.add_argument('--dry-run', action='store_true', help='match and report, send nothing')
    ap.add_argument('--include-tests', action='store_true', help='include self/test addresses')
    ap.add_argument('--bcc', help='comma-separated addresses to blind-copy on every digest')
    args = ap.parse_args()
    bcc = [e.strip() for e in args.bcc.split(',')] if args.bcc else None

    emails = _select_emails(args)
    if not emails:
        print("No emails selected.")
        return

    print(f"{'DRY RUN — ' if args.dry_run else ''}backfilling {len(emails)} email(s), "
          f"{args.days}d lookback:\n")
    sent = 0
    for email in emails:
        res = backfill_for_email(email, days=args.days, dry_run=args.dry_run, bcc=bcc)
        if res.get('matched_drops'):
            tag = 'WOULD SEND' if args.dry_run else ('SENT' if res['sent'] else 'NO-SEND')
            print(f"  [{tag}] {email}: {res['shown']} shown / {res['matched_drops']} matched")
            for m, src, url in (res.get('preview') or []):
                print(f"          ↳ {src} :: {', '.join(m)}")
            if res.get('sent'):
                sent += 1
        else:
            print(f"  [ -- ] {email}: no matches")
    if not args.dry_run:
        print(f"\nSent {sent} digest email(s).")


if __name__ == '__main__':
    main()
