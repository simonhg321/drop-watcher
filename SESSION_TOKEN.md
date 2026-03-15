DROP WATCHER SESSION 12+13 — 2026-03-14

Last commit: 7814a11 — Server hardening: paths.py central config, directory separation

All commits this session:
1. 9b88826 — Security: XSS + SSRF hardening, favicon, robots/sitemap, ops tooling
2. 288721e — Security + SRE: CORS, rate limiting, input validation, file locking, watchdog, BUG-005
3. d9e31e4 — Redesign index.html — open platform direction, origin story preserved
4. e5376b6 — index.html: padding below CTA button, center status bar
5. 57afb05 — Email UX overhaul, BUG-005 closed, BUG-006 fixed, verify page mobile button
6. 7814a11 — Server hardening: paths.py central config, directory separation

Completed this session:
- Full security audit: XSS, CORS, rate limiting, input validation, file locking, SSRF
- DMARC setup (p=quarantine via Cloudflare)
- BUG-005 + BUG-006 fixed
- watchdog.py — self-healing service monitor
- index.html redesign — public platform direction
- Email UX overhaul — all 3 user emails rewritten
- Server hardening — paths.py, code/config/data/logs separated
  - Config + secrets → /etc/drop-watcher (640, root:shg)
  - Data + PII → /var/lib/drop-watcher (700)
  - Logs → /var/log/drop-watcher (logrotate wired)
  - Supervisor conf updated with DW_* env vars
- .zshrc souped up — ir, dw, ship, pulls, logs, wstatus aliases
- hgr.html — build story easter egg page (not yet shipped)
- Multi-watch my-alerts — all watches for same email shown together
- bulk_watch.py — mass-created watches from sources.yaml
- check_users.sh + nuke_watchers.sh updated to new paths

Open items:
- Priority tuning — ai_interpreter.py calling standard CRK/Hinderer "high", should be "medium". Only special variants (damascus, collabs, limited editions) = HIGH.
- Playwright headless browser — JS-rendered sites (Blade HQ, KnifeCenter). Full session.
- Instagram layer — waiting on friends' account list
- UptimeRobot external monitoring
- Discord webhook for CRITICAL drops
- Browser sound alert on new CRITICAL
- Twilio A2P 10DLC (needs LLC EIN)
- UI cleanup — watchlist/my-alerts pages need polish

Say: "continuing Drop Watcher dev — here's my session token" and paste this block.
