# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
dealer_scout.py — discover NEW knife/EDC dealers that users add, classify them with
Haiku, and AUTO-ADD the confident ones to sources.yaml. Simon reviews weekly by email.

AUTO-ADD POLICY (set by Simon 2026-06-01 — supersedes the old review-queue-only design)
  A candidate is promoted to sources.yaml automatically when Haiku says is_dealer=YES
  AND confidence >= AUTO_ADD_CONFIDENCE. The is_dealer gate is the safety that keeps it
  honest: general marketplaces (target/walmart/amazon/ebay) classify is_dealer=NO even
  at 0.99 confidence, so they are never added. Promotion writes BOTH the repo
  config/sources.yaml and the live /etc copy, then restarts web_watcher (it only reads
  the curated list at startup). Simon gets a WEEKLY digest of everything auto-added and
  flags anything amiss with --reject.

  Caveat carried over from the old design: a curated source fans out to EVERY watcher on
  that domain (curated drops match by domain, not exact URL — see per_user_alerter). That
  fan-out is now the accepted, intended behaviour — the weekly review is the backstop.

WHAT IT DOES (cron, daily)
  1. Group active watchers by domain → distinct-user count + a sample URL.
  2. Skip domains already curated in sources.yaml, and domains re-checked recently.
  3. Ask Haiku (ai_interpreter.classify_dealer) "is this a knife/EDC dealer?".
  4. Upsert the verdict into dealer_candidates.
  5. Auto-add every pending dealer at/above the confidence bar; restart web_watcher.

CLI
  (cron)                    scan + classify + auto-add
  --digest                  email Simon the weekly review of auto-added dealers (cron weekly)
  --report                  print the current queue
  --approve <domain>        promote a candidate NOW (write to sources.yaml + reload)
  --reject  <domain>        mark a candidate rejected (won't be auto-added or shown again)
HGR
"""

import os
import sys
import re
import json
import shutil
import tempfile
import subprocess
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
import safe_fetch
import scam_gate
from ai_interpreter import classify_dealer
from alerter import send_email

SCOUT_EMAIL    = os.environ.get('DW_SCOUT_EMAIL') or os.environ.get('ALERT_TO')
RECHECK_DAYS    = 14         # re-classify a domain at most this often (saves tokens)
AUTO_ADD_CONFIDENCE = 0.80   # is_dealer AND conf >= this → auto-added to sources.yaml
DIGEST_DAYS     = 7          # weekly digest window

# Auto-add writes the repo copy (durable / git) AND the live copy (what web_watcher reads).
REPO_SOURCES = os.path.join(BASE_DIR, 'config', 'sources.yaml')
LIVE_SOURCES = paths.SOURCES_YAML

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [dealer_scout] %(levelname)s %(message)s',
    handlers=[logging.FileHandler(os.path.join(paths.LOG_DIR, 'dealer_scout.log')),
              logging.StreamHandler()]
)
log = logging.getLogger('dealer_scout')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; DropWatcher/1.0; +https://instockornot.club; instockornot)'}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def fetch_page(url, ssl_permissive=False):
    # SSRF-guarded shared fetch — this scrapes user-ADDED candidate domains, so an
    # unguarded GET here is the same hole we closed in web_watcher. (S52)
    return safe_fetch.fetch_text(url, max_bytes=MAX_RESPONSE_BYTES,
                                 ssl_permissive=ssl_permissive, headers=HEADERS, log=log)


from urls import domain_from_url  # single source of truth (shared matching normalizer)


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

    promoted = promote()
    log.info(f"scan done — {len(promoted)} dealer(s) auto-added")


def _dealer_name(domain):
    return domain.split('.')[0].replace('-', ' ').title()


def _source_entry_text(cand):
    """The sources.yaml block for an auto-added dealer (2-space list indentation)."""
    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    brands = cand['brands'] or '—'
    return (f"  # auto-added {today} by dealer_scout — {cand['category']} "
            f"(conf {cand['confidence']:.2f}; brands: {brands})\n"
            f"  - name: {_dealer_name(cand['domain'])}\n"
            f"    url: https://{cand['domain']}\n"
            f"    poll_interval: 20\n"
            f"    enabled: true")


def _atomic_write(path, text):
    """Write text to path atomically (temp in same dir + os.replace) so a concurrent
    reader — web_watcher loading the curated list — never sees a half-written file."""
    d = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.sources.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(tmp, path)   # atomic within the same filesystem
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_dealer_to_sources(cand):
    """Insert a dealer entry into the websites list (before the `feeds:` block) of the
    repo sources.yaml, validate it still parses, then mirror to the live /etc copy.
    Returns True only if both files were written cleanly. Never leaves a corrupt file."""
    try:
        with open(REPO_SOURCES) as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"auto-add: cannot read {REPO_SOURCES}: {e}")
        return False

    idx = next((i for i, l in enumerate(lines) if l.startswith('feeds:')), None)
    if idx is None:
        log.error("auto-add: no `feeds:` anchor in sources.yaml — aborting (won't guess)")
        return False

    new_text = ''.join(lines[:idx] + [_source_entry_text(cand) + '\n\n'] + lines[idx:])

    # Validate BEFORE touching disk — a corrupt sources.yaml would blind the watcher.
    try:
        data = yaml.safe_load(new_text)
        added = any(domain_from_url(w.get('url', '')) == cand['domain']
                    for w in data.get('websites', []))
        if not added:
            raise ValueError("entry not present after insert")
    except Exception as e:
        log.error(f"auto-add: insert would corrupt sources.yaml ({e}) — aborting")
        return False

    try:
        shutil.copyfile(REPO_SOURCES, REPO_SOURCES + '.bak')
        _atomic_write(REPO_SOURCES, new_text)
        if os.path.abspath(LIVE_SOURCES) != os.path.abspath(REPO_SOURCES):
            _atomic_write(LIVE_SOURCES, new_text)
    except Exception as e:
        log.error(f"auto-add: write failed for {cand['domain']}: {e}")
        return False
    return True


def _remove_dealer_from_sources(domain):
    """Reverse of _append: strip a dealer's entry (and its auto-added comment) from the
    websites list. Anchors on the url line, validates the result parses, mirrors to live.
    Returns True if removed, False if not present or the edit would corrupt the file."""
    try:
        with open(REPO_SOURCES) as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"remove: cannot read {REPO_SOURCES}: {e}")
        return False

    # Match by DOMAIN, not an exact `url: https://{domain}` string, so a curated
    # entry stored as www./with a path/http still gets removed (else --reject flips
    # the DB to rejected while the dealer stays live and keeps fanning out).
    u = None
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith('url:') and domain_from_url(s[4:].strip()) == domain:
            u = i
            break
    if u is None:
        return False  # not curated — nothing to strip

    start = u - 1                                   # the `- name:` line sits just above url
    if start >= 1 and lines[start - 1].lstrip().startswith('# auto-added'):
        start -= 1                                  # also drop its auto-added comment
    end = u + 1
    while end < len(lines) and lines[end].startswith('    '):   # poll_interval, enabled, …
        end += 1
    if end < len(lines) and lines[end].strip() == '':           # one trailing blank
        end += 1

    new_text = ''.join(lines[:start] + lines[end:])
    try:
        data = yaml.safe_load(new_text)
        if any(domain_from_url(w.get('url', '')) == domain for w in data.get('websites', [])):
            raise ValueError("domain still present after removal")
    except Exception as e:
        log.error(f"remove: edit would corrupt sources.yaml ({e}) — aborting")
        return False

    try:
        shutil.copyfile(REPO_SOURCES, REPO_SOURCES + '.bak')
        _atomic_write(REPO_SOURCES, new_text)
        if os.path.abspath(LIVE_SOURCES) != os.path.abspath(REPO_SOURCES):
            _atomic_write(LIVE_SOURCES, new_text)
    except Exception as e:
        log.error(f"remove: write failed for {domain}: {e}")
        return False
    log.info(f"removed {domain} from sources.yaml")
    return True


def _reload_web_watcher():
    """web_watcher reads the curated list only at startup, so a fresh dealer needs a
    restart to go live. shg has NOPASSWD on supervisorctl (verified 2026-06-01)."""
    try:
        r = subprocess.run(['sudo', '-n', '/usr/bin/supervisorctl', 'restart', 'web_watcher'],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            log.info("web_watcher restarted — new dealer(s) live")
            return True
        log.warning(f"web_watcher restart failed (rc={r.returncode}): {r.stderr.strip()} "
                    f"— new dealers go live on the next restart")
    except Exception as e:
        log.warning(f"web_watcher restart errored: {e} — new dealers go live on next restart")
    return False


def _promote_one(cand, override=False):
    """Add one candidate to sources.yaml and mark it promoted. Idempotent: a domain
    already curated is marked promoted without a second write.

    override=True: bypasses the scam gate (operator --approve is the human whitelist).
    override=False (default): runs scam_gate.evaluate before writing; a quarantine/review
    verdict rejects the candidate and emails the operator instead of writing to sources.yaml.
    """
    domain = cand['domain']
    if domain in curated_domains():
        log.info(f"{domain} already curated — marking promoted, no write")
        db.set_dealer_candidate_status(domain, 'promoted')
        db.mark_dealer_candidate_notified(domain)
        return False

    if not override:
        cand_url = cand.get('sample_url') or f"https://{domain}"
        verdict = scam_gate.evaluate(domain, cand_url, fetch_page, log=log)
        if verdict.action != "ingest":
            log.warning(f"SCAM GATE blocked {domain}: action={verdict.action} "
                        f"score={verdict.score} reasons={verdict.reasons}")
            db.set_dealer_candidate_status(domain, 'rejected')
            scam_gate.notify_operator(domain, cand_url, verdict, send_email)
            return False
    else:
        log.info(f"{domain} — operator override, skipping scam gate")

    if not _append_dealer_to_sources(cand):
        return False
    db.set_dealer_candidate_status(domain, 'promoted')
    db.mark_dealer_candidate_notified(domain)   # stamp = "surfaced to Simon" → drives the digest
    log.info(f"AUTO-ADDED {domain} (conf {cand['confidence']:.2f}, {cand['category']})")
    send_dealer_alert(cand)                      # instant heads-up (best-effort; never undoes the add)
    return True


def promote():
    """Auto-add every pending dealer at/above the confidence bar. Returns added domains."""
    added = []
    for cand in db.get_dealer_candidates(status='pending', dealers_only=True):
        if cand['confidence'] < AUTO_ADD_CONFIDENCE:
            continue
        if _promote_one(cand):
            added.append(cand['domain'])
    if added:
        _reload_web_watcher()
    return added


def send_dealer_alert(cand):
    """Instant heads-up the moment a NEW knife dealer is confirmed + auto-added.
    Best-effort: a send failure is logged, never raised — it must not undo the add.
    The weekly digest (send_digest) still runs as a roundup/backstop."""
    try:
        d      = html_mod.escape(cand['domain'])
        name   = html_mod.escape(_dealer_name(cand['domain']))
        cat    = html_mod.escape(cand.get('category') or '')
        brands = html_mod.escape(cand.get('brands') or '—')
        conf   = cand.get('confidence') or 0
        subj = f"🔪 New knife dealer auto-added: {cand['domain']}"
        html = (f'<div style="font-family:monospace;background:#0a0a0a;color:#e8e8e8;'
                f'padding:24px;max-width:600px;">'
                f'<h2 style="color:#e67e22;margin:0 0 6px;">🔪 DEALER SCOUT — NEW DEALER</h2>'
                f'<p style="color:#ddd;">Just confirmed a knife/EDC dealer we weren\'t watching '
                f'and auto-added it to the watch list (is_dealer + conf ≥ {AUTO_ADD_CONFIDENCE:.0%}).</p>'
                f'<div style="background:#161616;border:1px solid #222;padding:14px;margin:8px 0;">'
                f'<div style="color:#fff;font-size:15px;">{name} '
                f'<span style="color:#666;font-size:12px;">· https://{d}</span></div>'
                f'<div style="color:#888;font-size:12px;margin-top:4px;">{cat} · conf {conf:.2f} '
                f'· brands: {brands}</div>'
                f'<div style="color:#555;font-size:11px;margin-top:6px;">'
                f'back out: <code>dealer_scout.py --reject {d}</code></div>'
                f'</div></div>')
        txt = (f"DEALER SCOUT — new knife dealer auto-added:\n\n"
               f"  {_dealer_name(cand['domain'])}  https://{cand['domain']}\n"
               f"  {cand.get('category') or ''} · conf {conf:.2f} · brands: {cand.get('brands') or '-'}\n\n"
               f"Back out: dealer_scout.py --reject {cand['domain']}")
        if send_email(subj, html, txt, to_addr=SCOUT_EMAIL):
            log.info(f"instant dealer alert sent — {cand['domain']}")
        else:
            log.error(f"instant dealer alert failed — {cand['domain']}")
    except Exception as e:
        log.error(f"instant dealer alert error for {cand.get('domain')}: {e}")


def send_digest():
    """Weekly email: every dealer auto-added in the last DIGEST_DAYS. Always sends (a
    quiet 'nothing this week' is a heartbeat that the scout is alive and reviewed)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DIGEST_DAYS)
    recent = []
    for c in db.get_dealer_candidates(status='promoted'):
        try:
            if c.get('notified') and datetime.fromisoformat(c['notified']) >= cutoff:
                recent.append(c)
        except ValueError:
            continue
    recent.sort(key=lambda c: c['confidence'], reverse=True)
    subj, html, txt = build_digest_email(recent)
    if send_email(subj, html, txt, to_addr=SCOUT_EMAIL):
        log.info(f"weekly digest sent — {len(recent)} auto-added dealer(s)")
    else:
        log.error("weekly digest email failed")


def build_digest_email(rows):
    n = len(rows)
    subj = f"🔎 Dealer scout — {n} new dealer{'s' if n != 1 else ''} added this week"
    if rows:
        cards = ''
        for c in rows:
            d = html_mod.escape(c['domain'])
            cards += f"""
            <div style="background:#161616;border:1px solid #222;padding:14px;margin:0 0 10px;">
              <div style="color:#fff;font-size:14px;">{html_mod.escape(_dealer_name(c['domain']))}
                <span style="color:#666;font-size:12px;">· https://{d}</span></div>
              <div style="color:#888;font-size:12px;margin-top:4px;">
                {html_mod.escape(c['category'] or '')} · conf {c['confidence']:.2f}
                · brands: {html_mod.escape(c['brands'] or '—')}</div>
              <div style="color:#555;font-size:11px;margin-top:6px;">
                back out: <code>dealer_scout.py --reject {d}</code></div>
            </div>"""
        body_html = (f'<p style="color:#ddd;">I auto-added <b style="color:#fff;">{n}</b> '
                     f'knife/EDC dealer{"s" if n != 1 else ""} to the watch list this week '
                     f'(is_dealer + confidence ≥ {AUTO_ADD_CONFIDENCE:.0%}). Scan and flag '
                     f'anything off — reject backs it out of sources.yaml.</p>{cards}'
                     f'<p style="color:#555;font-size:11px;">URLs default to the bare domain; '
                     f'tell me if any should point at a specific drops/new-arrivals page.</p>')
        txt_lines = [f"- {_dealer_name(c['domain'])}  https://{c['domain']}\n"
                     f"    {c['category']} · conf {c['confidence']:.2f} · brands: {c['brands'] or '-'}\n"
                     f"    reject: dealer_scout.py --reject {c['domain']}" for c in rows]
        txt = (f"DEALER SCOUT — {n} dealer(s) auto-added this week "
               f"(is_dealer + conf >= {AUTO_ADD_CONFIDENCE:.0%}):\n\n" + "\n".join(txt_lines)
               + "\n\nReject any to back it out of sources.yaml.")
    else:
        body_html = ('<p style="color:#ddd;">No new dealers crossed the auto-add bar this '
                     f'week (is_dealer + confidence ≥ {AUTO_ADD_CONFIDENCE:.0%}). Nothing to review.</p>')
        txt = "DEALER SCOUT — no new dealers auto-added this week. Nothing to review."
    html = (f'<div style="font-family:monospace;background:#0a0a0a;color:#e8e8e8;'
            f'padding:24px;max-width:600px;"><h2 style="color:#e67e22;margin:0 0 6px;">'
            f'🔎 DEALER SCOUT — WEEKLY</h2>'
            f'<p style="color:#aaa;font-size:13px;margin:0 0 18px;">instockornot.club</p>'
            f'{body_html}</div>')
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
    elif '--digest' in sys.argv:
        send_digest()
    elif '--approve' in sys.argv:
        domain = sys.argv[sys.argv.index('--approve') + 1]
        cand = db.get_dealer_candidate(domain)
        if not cand:
            print(f"no candidate for {domain}")
        elif _promote_one(cand, override=True):
            _reload_web_watcher()
            print(f"promoted {domain} → sources.yaml")
        else:
            print(f"{domain} not written (already curated or write failed — see log)")
    elif '--reject' in sys.argv:
        domain = sys.argv[sys.argv.index('--reject') + 1]
        db.set_dealer_candidate_status(domain, 'rejected')
        if _remove_dealer_from_sources(domain):
            _reload_web_watcher()
            print(f"rejected {domain} + removed from sources.yaml")
        else:
            print(f"rejected {domain} (was not in sources.yaml)")
    else:
        scan()
