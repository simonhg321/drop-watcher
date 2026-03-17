DROP WATCHER SESSION 15 — 2026-03-16

Last commit: v1.0 (bafb90b) + README update pushed to GitHub

Completed this session:
- v1.0 tagged and pushed to GitHub (git+SSH set up)
- Announced on Reddit and FB Underground knife community
- Jonathan McNees (maker) called — approves of Drop Watcher, spreading word at Texas knife show
- Project restructured: html/, conf/, bin/ — clean separation
  - All HTML moved to html/, favicon/robots/sitemap too
  - conf/drop-watcher.conf (was in bin/)
  - check_users.sh and nuke_watchers.sh moved to bin/
  - Dead files nuked: orchestrator.py, watcher_status.html, web/, test files, .cleanup.sh, .zshrc
  - BUG-007 and BUG-008 resolved
- Gunicorn bumped to 5 workers for traffic
- sync_ironman.sh — one-command deploy script
- ship alias updated for new structure, push() function added to .zshrc
- index.html landing page rewritten — friendly copy, kept dark aesthetic
  - Green START WATCHING button in hero and nav
  - "Never miss a drop" / three steps / promises / use cases / stack
- Confirmation email layout fixed — VIEW MY ALERTS button on top
- Verify-check no longer writes false drops to drops.jsonl
- my-alerts.html — matched drops moved to top of page
- robots.txt and sitemap.xml cleaned up (removed dead pages, added hgr.html)
- HANDOFF.md — full project map for future-Simon
- handoff-sms.md — SMS wiring handoff for Claude.ai
- watcher_io.py — shared watchers.json I/O with file locking (extracted from 3 files)
- Admin dashboard (watcher_status.html) — IP-locked, shows all watchers, stats, system health
  - /api/watchers expanded: total, active, pending, unique emails, per-watcher detail
  - Apache + Python dual IP check (home IP + localhost)
- discord_logger.py — posts drops to Discord webhook, dedup tracking, cron ready
  - Webhook: https://discord.com/api/webhooks/1483119340478795928/vEgBeMtiq2rgb8xBWnxjxUWabVrK8-nlFGZbCI7tevQ6kXzOdyraduaN-iXDd97wMrMr
- 21 watch cap per email — prevents abuse
- cleanup_stale.py — nukes pending watches older than 48h (cron daily 4:05am)
- GoAccess stats regenerating hourly on ironman
- DMARC report reviewed — perfect score, all PASS
- Git SSH set up to GitHub, remote switched from HTTPS to SSH
- /etc/hosts: ironman alias added on mac

Known issues:
- Gmail sometimes spams verification emails (DMARC is clean, reputation building)
- Twilio A2P 10DLC still pending

Open items:
- Twilio SMS wiring — once A2P approved (handoff-sms.md ready)
- Playwright headless browser — JS-rendered sites (Blade HQ, KnifeCenter)
- Instagram layer — waiting on friends' account list
- UptimeRobot external monitoring
- Discord logger — deployed, needs first real drop to test
- Browser sound alert on new CRITICAL
- Phase 2: admin dashboard pagination/search/group-by-email
- Phase 2: keyword hover tooltip — show AI reasoning per keyword
- Phase 2: email templates extraction, Resend wrapper, watcher_signup.py route splitting
- Phase 2: SQLite migration when file-based I/O becomes bottleneck
- alerts.html still uses old design system (status.html deleted)
- Collection showcase idea — share knife collection (Discord channel or site page)

Say: "continuing Drop Watcher dev — here's my session token" and paste this block.
