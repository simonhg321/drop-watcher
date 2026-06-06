#!/usr/bin/env python3
"""One-off announcement / re-engagement email to active Drop Watcher users.

Modes:
  (no flag)        DRY RUN — list recipients, send nothing.
  --test ADDR      send ONLY to ADDR (uses that user's real unsub token if present).
  --send           send to ALL distinct active real users (excludes internal accounts).

From: Drop Watcher <alerts@instockornot.club>   Reply-To: simon@instockornot.club
Each recipient gets their own one-click unsubscribe link (CAN-SPAM).
"""
import os, sys, sqlite3, httpx, yaml

DB = os.environ.get("DW_DATA_DIR", "/var/lib/drop-watcher") + "/dropwatcher.db"
SOURCES_YAML = os.environ.get("DW_CONFIG_DIR", "/etc/drop-watcher") + "/sources.yaml"
ENV_FILE = os.environ.get("DW_ENV_FILE", "/etc/drop-watcher/.env")
FROM_ADDRESS = "Drop Watcher <alerts@instockornot.club>"
REPLY_TO = "simon@instockornot.club"
RESEND_API_URL = "https://api.resend.com/emails"

# Internal/test accounts never included in --send
EXCLUDE = {"simonhg@gmail.com", "simon@instockornot.club", "gibson.simon1@gmail.com"}

SUBJECT = "New in Drop Watcher: watch a maker, not a page"


def load_env(path):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def unsub_url(token):
    return f"https://instockornot.club/api/unsubscribe/{token}"


_N_SOURCES = None


def source_count():
    """Live count of the sources we actually scrape: enabled websites + feeds
    (sources.yaml). Cached. Falls back to '' on any read error so the copy never
    prints a bogus 0."""
    global _N_SOURCES
    if _N_SOURCES is None:
        try:
            d = yaml.safe_load(open(SOURCES_YAML)) or {}
            sites = [x for x in (d.get("websites") or []) if (x or {}).get("enabled", True)]
            _N_SOURCES = len(sites) + len(d.get("feeds") or [])
        except Exception:
            _N_SOURCES = 0
    return _N_SOURCES or ""


def body_text(token):
    return f"""Hey —

Quick one. You can now set a watch without hunting down a URL. You can use
your own URL, or our entire list of {source_count()} sources we scrape.

Just tell Drop Watcher a maker (e.g. Chris Reeve) and the thing you're after
(damascus, CGG, Sebenza 25) — that's it. We'll watch every knife shop we
track. The instant it shows up anywhere, you get the alert.

Still want to watch one specific page? That works exactly like before.

Set one up: https://instockornot.club/watchlist.html

— Simon
instockornot.club

—
You're getting this because you have an active watch at instockornot.club.
Unsubscribe: {unsub_url(token)}
"""


def body_html(token):
    # Deliberately minimal markup — plain paragraphs, no card/colors/lists — so Gmail
    # reads it as a personal email (Primary) rather than a styled marketing blast (Promotions).
    return f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;line-height:1.5">
<p>Hey — Simon here, the guy who built Drop Watcher.</p>
<p>You're one of the first group of people using Drop Watcher, so I wanted to reach out personally and say thank you. Your watches are live and working — the system's been busy lately (160+ drops a day across the sites we track).</p>
<p>I started Drop Watcher because I wanted to build things again, and because I wanted something like it to find knives for me. I figured if I'm going to build it for myself, all I really need to do to share it is have a slightly more robust email solution — and that was really it. It doesn't cost much to run, and I love that people are using it.</p>
<p>A couple of things that got better recently:</p>
<p>Alerts now deep-link straight to the matched product — not just the store page. Less hunting, faster to the "add to cart."</p>
<p>New "cool makers" list — every maker we track, grouped by tier. We now look at the maker and distributor URLs that users enter, and if we haven't seen them before and they focus on knives, we add them to the database. That means we get better over time. You can grab our list of makers here: <a href="https://instockornot.club/our-cool-makers.html">https://instockornot.club/our-cool-makers.html</a></p>
<p>The small ask: Drop Watcher is free, and word-of-mouth is the only way it grows. If you know other knife/EDC people who are tired of missing drops, send them the link — https://instockornot.club. If you're in forums with others who might be interested, please spread the link. The site gets better the more people use it.</p>
<p>Thanks for being here early. Reply to this anytime — it comes to me.</p>
<p>— Simon<br>simon@instockornot.club</p>
<p style="font-size:12px;color:#888">You're getting this because you have an active watch at instockornot.club. <a href="{unsub_url(token)}" style="color:#888">Unsubscribe</a></p>
</div>"""


def send_one(api_key, to_addr, token):
    u = unsub_url(token)
    # Text-only (no html part) is the strongest "personal email" signal to Gmail's
    # tab classifier. List-Unsubscribe kept for spam-folder safety / compliance.
    payload = {
        "from": FROM_ADDRESS,
        "to": [to_addr],
        "reply_to": REPLY_TO,
        "subject": SUBJECT,
        "text": body_text(token),
        "headers": {
            "List-Unsubscribe": f"<{u}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    r = httpx.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("id", "?")


def recipients(conn, only=None):
    cur = conn.execute(
        "SELECT email, unsubscribe_token FROM watchers WHERE active=1 GROUP BY email"
    )
    rows = []
    for email, token in cur.fetchall():
        if only is not None:
            if email == only:
                rows.append((email, token))
        elif email not in EXCLUDE:
            rows.append((email, token))
    return rows


def main():
    load_env(ENV_FILE)
    api_key = os.environ.get("RESEND_API_KEY")
    conn = sqlite3.connect(DB)

    if "--test" in sys.argv:
        addr = sys.argv[sys.argv.index("--test") + 1]
        rows = recipients(conn, only=addr)
        if not rows:  # addr not an active watcher — still send test with a dummy token
            rows = [(addr, "TESTTOKEN")]
        for email, token in rows:
            mid = send_one(api_key, email, token)
            print(f"TEST sent → {email}  (resend id {mid})")
        return

    rows = recipients(conn)
    if "--send" not in sys.argv:
        print(f"DRY RUN — {len(rows)} recipients (no email sent):")
        for email, _ in rows:
            print("  ", email)
        print("\nRe-run with --send to deliver, or --test ADDR for a single test.")
        return

    print(f"SENDING to {len(rows)} recipients…")
    ok = 0
    for email, token in rows:
        try:
            mid = send_one(api_key, email, token)
            ok += 1
            print(f"  ✓ {email}  ({mid})")
        except Exception as e:
            print(f"  ✗ {email}  ERROR: {e}")
    print(f"Done: {ok}/{len(rows)} sent.")


if __name__ == "__main__":
    main()
