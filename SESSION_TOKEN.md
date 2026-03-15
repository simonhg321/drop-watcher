DROP WATCHER SESSION 14 — 2026-03-15

Last commit: (uncommitted — ship ran, changes on ironman)

Completed this session:
- Shared token model — one email = one token = one dashboard
  - normalize_tokens.py unified 56 watches under one token
  - Signup reuses token, auto-activates if email already verified
  - Verify/unsubscribe affect ALL watches for that email
  - STOP individual watch uses watch ID
- per_user_alerter.py rewritten — reads drops.jsonl, no re-scraping
  - Cooldown per watcher+URL+keyword combo, not per watcher globally
  - per_user_sent.json tracks with 24h auto-prune
- trim_drops.py — 30-day retention, cron daily at 4am
- UI unification — Bebas Neue / Share Tech Mono / Crimson Pro everywhere
  - index.html, watchlist.html, my-alerts.html, get-my-link.html unified
  - Consistent nav: Watch, My Alerts, GET MY LINK
- privacy.html — full rewrite with Twilio A2P 10DLC SMS compliance
- Alert emails now include "My Alerts Dashboard" button
- Cron log paths all fixed to /var/log/drop-watcher/
- cleanup_ironman.sh ready (dead files removal)
- support@instockornot.club alias live
- BUGS.md: BUG-007 (web/ dir), BUG-008 (orchestrator.py)
- First real drop caught — Strider knives, full pipeline worked

Known issues:
- Gmail sometimes spams verification emails
- Twilio A2P 10DLC pending — expected Monday 2026-03-16
- web/ directory still on ironman (cleanup script ready)
- Changes not committed to git yet

Open items:
- Twilio SMS wiring — once A2P approved
- Playwright headless browser — JS-rendered sites (Blade HQ, KnifeCenter)
- Instagram layer — waiting on friends' account list
- UptimeRobot external monitoring
- Discord webhook for CRITICAL drops
- Browser sound alert on new CRITICAL
- alerts.html and status.html still use old design system
- BUG-007: delete web/ directory
- BUG-008: delete orchestrator.py

Say: "continuing Drop Watcher dev — here's my session token" and paste this block.
