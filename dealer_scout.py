# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
dealer_scout.py — surface NEW knife/EDC dealers that users keep adding but we don't
yet curate, so Simon can decide whether to promote them to sources.yaml.

WHY THIS IS A REVIEW QUEUE, NOT AN AUTO-ADDER
  A curated source in sources.yaml fans out to EVERY watcher on that domain (curated
  drops match by domain, not exact URL — see per_user_alerter). Auto-promoting an
  unreviewed domain could therefore spray cross-watcher noise, or pull a general
  marketplace (target.com, ebay.com) a user happened to add into the curated fan-out.
  So this script ONLY writes to the dealer_candidates review queue. It never touches
  sources.yaml. Promotion stays a deliberate, human step — that is the collision guard.

WHAT IT DOES (cron, daily)
  1. Group active watchers by domain → distinct-user count + a sample URL.
  2. Skip domains already curated in sources.yaml, and domains re-checked recently.
  3. Ask Haiku (ai_interpreter.classify_dealer) "is this a knife/EDC dealer?".
  4. Upsert the verdict into dealer_candidates.
  5. Nudge Simon ONCE per domain when a real dealer crosses NUDGE_MIN_USERS distinct users.

CLI
  (cron)                    scan + classify + nudge
  --report                  print the current queue
  --approve <domain>        mark a candidate approved (status only; still not watched)
  --reject  <domain>        mark a candidate rejected (won't nudge again)
HGR
"""

import os
import sys
import re
import json
import html as html_mod
import logging
from datetime import datetime, timezone, timedelta

import requests
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'agents'))

import paths
import db
import collection_fetch
from ai_interpreter import classify_dealer
from alerter import send_email

SCOUT_EMAIL    = os.environ.get('DW_SCOUT_EMAIL') or os.environ.get('ALERT_TO')
NUDGE_MIN_USERS = 2          # distinct users on a domain before we nudge Simon
RECHECK_DAYS    = 14         # re-classify a domain at most this often (saves tokens)
MIN_CONFIDENCE  = 0.6        # below this we don't nudge, even if is_dealer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [dealer_scout] %(levelname)s %(message)s',
    handlers=[logging.FileHandler(os.path.join(paths.LOG_DIR, 'dealer_scout.log')),
              logging.StreamHandler()]
)
log = logging.getLogger('dealer_scout')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; personal use)'}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def fetch_page(url, ssl_permissive=False):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True,
                         verify=not ssl_permissive)
        r.raise_for_status()
        content = r.content[:MAX_RESPONSE_BYTES]
        r.close()
        return content.decode('utf-8', errors='replace')
    except requests.RequestException as e:
        log.warning(f"fetch failed {url}: {e}")
        return None


def domain_from_url(url):
    u = (url or '').lower().replace('https://', '').replace('http://', '')
    if u.startswith('www.'):
        u = u[4:]
    return u.split('/')[0]


def curated_domains():
    try:
        s = yaml.safe_load(open(paths.SOURCES_YAML))
    except Exception as e:
        log.error(f"could not read sources.yaml: {e}")
        return set()
    return {domain_from_url(w['url']) for w in s.get('websites', []) if w.get('url')}


def domains_from_watchers():
    """domain -> {users: set(email), sample_url}."""
    out = {}
    for w in db.get_active_watchers():
        url = (w.get('url') or '').strip()
        if not url:
            continue
        d = domain_from_url(url)
        if not d:
            continue
        entry = out.setdefault(d, {'users': set(), 'sample_url': url})
        entry['users'].add((w.get('email') or '').lower())
    return out


def _recently_checked(domain):
    cand = db.get_dealer_candidate(domain)
    if not cand or not cand.get('last_checked'):
        return False
    try:
        last = datetime.fromisoformat(cand['last_checked'])
    except ValueError:
        return False
    return datetime.now(timezone.utc) - last < timedelta(days=RECHECK_DAYS)


def scan():
    curated = curated_domains()
    found = domains_from_watchers()
    log.info(f"{len(found)} user domains; {len(curated)} curated; classifying new ones")

    for domain, info in found.items():
        if domain in curated:
            continue
        user_count = len(info['users'])
        if _recently_checked(domain):
            # refresh only the user_count without re-spending tokens
            cand = db.get_dealer_candidate(domain)
            db.upsert_dealer_candidate(
                domain, cand['is_dealer'], cand['category'], cand['brands'],
                cand['confidence'], cand['reason'], cand['sample_url'], user_count)
            continue

        sample = info['sample_url']
        text = collection_fetch.fetch_collection_text(sample, fetch_page, log=log)
        if not text:
            log.warning(f"{domain} — could not fetch sample {sample}, skipping")
            continue

        verdict = classify_dealer(sample, text)
        if not verdict:
            log.warning(f"{domain} — classifier returned nothing, skipping")
            continue

        brands = ', '.join(verdict.get('brands') or [])
        db.upsert_dealer_candidate(
            domain,
            is_dealer=bool(verdict.get('is_dealer')),
            category=verdict.get('category', ''),
            brands=brands,
            confidence=float(verdict.get('confidence') or 0),
            reason=verdict.get('reason', ''),
            sample_url=sample,
            user_count=user_count,
        )
        log.info(f"{domain} — dealer={verdict.get('is_dealer')} "
                 f"conf={verdict.get('confidence')} users={user_count} ({verdict.get('category','')})")

    nudge()
    log.info("scan done")


def _yaml_snippet(cand):
    name = cand['domain'].split('.')[0].replace('-', ' ').title()
    return (f"  - name: {name}\n"
            f"    url: https://{cand['domain']}\n"
            f"    poll_interval: 20\n"
            f"    enabled: true")


def nudge():
    """Email Simon once per qualifying dealer candidate."""
    for cand in db.get_dealer_candidates(status='pending', dealers_only=True):
        if cand.get('notified'):
            continue
        if cand['user_count'] < NUDGE_MIN_USERS or cand['confidence'] < MIN_CONFIDENCE:
            continue
        subj, html, txt = build_nudge_email(cand)
        if send_email(subj, html, txt, to_addr=SCOUT_EMAIL):
            db.mark_dealer_candidate_notified(cand['domain'])
            log.info(f"nudged Simon about {cand['domain']} ({cand['user_count']} users)")
        else:
            log.error(f"nudge email failed for {cand['domain']}")


def build_nudge_email(cand):
    d = html_mod.escape(cand['domain'])
    brands = html_mod.escape(cand['brands'] or '—')
    cat = html_mod.escape(cand['category'] or '')
    reason = html_mod.escape(cand['reason'] or '')
    snippet = html_mod.escape(_yaml_snippet(cand))
    subj = f"🔎 New dealer candidate — {cand['domain']} ({cand['user_count']} users)"
    html = f"""
    <div style="font-family:monospace;background:#0a0a0a;color:#e8e8e8;padding:24px;max-width:600px;">
      <h2 style="color:#e67e22;margin:0 0 6px;">🔎 DEALER SCOUT</h2>
      <p style="color:#aaa;font-size:13px;margin:0 0 18px;">instockornot.club</p>
      <p><b style="color:#fff;">{cand['user_count']} different users</b> are watching pages on
      <b style="color:#fff;">{d}</b> — a domain we don't curate yet.</p>
      <div style="background:#161616;border:1px solid #222;padding:16px;margin:16px 0;">
        <div style="color:#555;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;">Haiku verdict</div>
        <div style="margin-top:6px;">Knife/EDC dealer: <b style="color:#39d98a;">yes</b>
          &nbsp;·&nbsp; confidence {cand['confidence']:.2f} &nbsp;·&nbsp; {cat}</div>
        <div style="color:#888;font-size:12px;margin-top:6px;">Brands seen: {brands}</div>
        <div style="color:#888;font-size:12px;margin-top:6px;">{reason}</div>
      </div>
      <p style="color:#aaa;font-size:13px;">If you want to curate it, paste this into
        <code>sources.yaml</code> under <code>websites:</code> —</p>
      <pre style="background:#111;border:1px solid #222;padding:12px;color:#cfe8cf;font-size:12px;overflow:auto;">{snippet}</pre>
      <p style="color:#b06; font-size:12px;">⚠ Curated sources fan out to every watcher on
        the domain — that's the intended leverage, but it's why this is your call, not automatic.</p>
      <p style="color:#444;font-size:11px;">Reject future nudges:
        <code>python3 dealer_scout.py --reject {d}</code></p>
    </div>"""
    txt = (f"DEALER SCOUT — new candidate\n\n"
           f"{cand['user_count']} users watch {cand['domain']} (uncurated).\n"
           f"Haiku: knife/EDC dealer, confidence {cand['confidence']:.2f}, {cand['category']}\n"
           f"Brands: {cand['brands'] or '-'}\n{cand['reason']}\n\n"
           f"To curate, add to sources.yaml under websites:\n{_yaml_snippet(cand)}\n\n"
           f"NOTE: curated sources fan out to every watcher on the domain — your call.\n"
           f"Reject: python3 dealer_scout.py --reject {cand['domain']}")
    return subj, html, txt


def report():
    rows = db.get_dealer_candidates()
    if not rows:
        print("No dealer candidates yet."); return
    print(f"{'domain':32} {'dealer':6} {'conf':5} {'users':5} {'status':9} category")
    print("-" * 90)
    for c in rows:
        print(f"{c['domain']:32} {('YES' if c['is_dealer'] else 'no'):6} "
              f"{c['confidence']:.2f}  {c['user_count']:>4}  {c['status']:9} "
              f"{c['category']}  {('['+c['brands']+']') if c['brands'] else ''}")


if __name__ == '__main__':
    if '--report' in sys.argv:
        report()
    elif '--approve' in sys.argv:
        db.set_dealer_candidate_status(sys.argv[sys.argv.index('--approve') + 1], 'approved')
        print("approved")
    elif '--reject' in sys.argv:
        db.set_dealer_candidate_status(sys.argv[sys.argv.index('--reject') + 1], 'rejected')
        print("rejected")
    else:
        scan()
