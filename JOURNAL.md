# Drop Watcher Dev Journal
# instockornot.club | /home/shg/drop-watcher/

---

## HOW TO START A SESSION
1. Run this on the server:
```
echo "=== JOURNAL ===" && cat /home/shg/drop-watcher/JOURNAL.md
echo "=== RECENT DROPS ===" && tail -5 /home/shg/drop-watcher/drops.jsonl
echo "=== ALERT COUNTS ===" && grep -c "priority-critical\|priority-high\|priority-medium" /var/www/html/alerts.html 2>/dev/null || echo "no alerts.html"
echo "=== WATCHER STATUS ===" && sudo supervisorctl status
```
2. Paste output to Claude and say: "continuing Drop Watcher dev"

---

## CURRENT STATUS — 2026-03-07

**Active bugs (fix these first):**
- BUG-001: ✓ FIXED 2026-03-07 — OVERRIDE RULE added to ai_interpreter.py PRIORITY RULES
- BUG-002: ✓ FIXED 2026-03-07 — content hash dedup added to web_watcher.py (4hr suppression window)
- BUG-003: ✓ FIXED 2026-03-07 — OVERRIDE language added to Arno Bernard rule in ai_interpreter.py
- BUG-004: AZ Custom Knives Steel Flame page not in sources.yaml — add https://www.arizonacustomknives.com/knives-by-maker/steel-flame/

**Last confirmed working:**
- Alert sort: newest-first within priority groups (generate_alerts.py ~line 64) — APPLIED, not yet verified
- Reddit RSS: r/bladesinstock, r/knife_swap active. r/knifeclub, r/EDC disabled (noise)
- Priority rules: Hinderer x SF / CRK x WC / Strider x SF = CRITICAL. MSC = CRITICAL. McNees drop banner = HIGH.

---

## FEATURE BACKLOG

- [ ] Email subscription — Flask → magic link auth → BCC on alerts → unsubscribe
- [x] Morning briefer wired to cron 7am daily — 2026-03-07
- [ ] Instagram layer — waiting on friends' list of ~200-300 secondary market accounts
- [x] Messerteam.de Arno Bernard page added to sources.yaml — 2026-03-07
- [x] Rike Knife disabled in sources.yaml — 2026-03-07
- [ ] Frontend priority override UI (manual CRITICAL/MEDIUM toggle on alerts.html)

---

## ARCHITECTURE REFERENCE

### Daemons (supervisord)
- web_watcher.py — scrapes monitored URLs, strips nav/header/footer, feeds ai_interpreter.py

### Cron
- */15  feed_watcher.py       — Reddit RSS (r/bladesinstock, r/knife_swap)
- */2   generate_alerts.py    — builds /var/www/html/alerts.html
- */30  alerter.py            — emails CRITICAL/HIGH alerts
- 7am   alerter.py digest     — daily summary email
- hourly preflight.py         — builds /var/www/html/status.html

### Key files
- agents/ai_interpreter.py   — AI analysis + PRIORITY RULES section
- agents/feed_watcher.py     — Reddit RSS watcher
- agents/web_watcher.py      — web scraper daemon
- generate_alerts.py         — alerts HTML generator
- config/sources.yaml        — all monitored URLs
- config/makers.yaml         — maker priority config
- /var/www/html/alerts.html  — live alerts page
- /var/www/html/status.html  — preflight health check

---

## PRIORITY RULES (current)

CRITICAL:
- Hinderer x Steel Flame collab
- CRK x Wilson Combat collab
- Strider x Steel Flame collab
- Any Mick Strider Custom Knife (MSC) available for purchase
- (NOT other collabs — those are MEDIUM)

HIGH:
- McNees Knives drop announcement or DROP banner
- Arno Bernard damascus or mammoth inlay variants

MEDIUM:
- All recurring scheduled drops (any maker, any time)
- Standard Arno Bernard production (iMamba, Rinkhals, Turaco without special materials)
- All other collabs not listed above

---

## SESSION LOG

### Session 1 — 2026-03-06
- Initial build: web_watcher.py, ai_interpreter.py, generate_alerts.py
- sources.yaml, makers.yaml populated
- Supervisord config, cron schedule

### Session 2 — 2026-03-06
- feed_watcher.py (Reddit RSS)
- Nav stripping in web_watcher.py (BeautifulSoup)
- Priority rules tightened
- Secondary market sources added to sources.yaml
- Mick Strider Custom Knives added

### Session 3 — 2026-03-07
- Alert sort fix applied (not yet verified)
- BUG-001 through BUG-004 identified from live alerts.html review
- JOURNAL.md created, session starter command established


### Session 4 — 2026-03-07
- BUG-001 fixed: OVERRIDE RULE added to ai_interpreter.py — recurring drops cap at MEDIUM
- BUG-002 fixed: content hash dedup added to web_watcher.py — 4hr suppression window
- BUG-003 fixed: Arno Bernard OVERRIDE language strengthened in ai_interpreter.py
- BUG-004 fixed: AZ Custom Knives Steel Flame page added to sources.yaml
- validate_watcher alias added to ~/.bashrc
- JOURNAL.md session system established

### Session 4 continued — 2026-03-07
- Morning briefer wired: morning_briefer.py created, tested, cron 0 7 * * *
- First email delivered successfully via Resend
- [x] Messerteam.de added to sources.yaml
- [x] Rike Knife disabled in sources.yaml

### Session 4 final — 2026-03-07
- backup_drop_watcher.sh created — tarballs ~/backups, keeps last 7
- Weekly cron wired: 0 3 * * 0
- First backup verified: extracted and confirmed complete on MacBook
- scp command: scp 'shg@instockornot.club:~/backups/drop-watcher_*.tar.gz' ~/drop-watcher-backups/

### Session 5 — 2026-03-07
**Priority rule changes (ai_interpreter.py):**
- Hinderer wood/walnut handles → HIGH (was CRITICAL)
- CRK non-WC-collab drops → HIGH (was CRITICAL)
- Demko AD20.5 → MEDIUM (common production knife)
- Sold-out items never included in notable_items
- Pro-Tech x Chaves → HIGH (not a designated CRITICAL collab)

**generate_alerts.py rewritten:**
- Dedup baked in — one entry per source across full 48h window
- Reddit deduped per-hour (different posts)
- Best priority wins when merging; notable_items merged across entries
- Sort: priority groups, newest-first within each group

**drops.jsonl cleaned:**
- Removed/downgraded stale bad entries from before fixes
- Page now shows ~25 clean alerts vs 115 stacked entries

**Active bugs cleared this session — none remaining**

**CURRENT PRIORITY RULES:**
- CRITICAL: Hinderer x SF collab, CRK x Wilson Combat, Strider x SF, MSC available for purchase
- HIGH: Hinderer wood/walnut/brass/copper handles, CRK specials (non-WC), McNees drop banner, Damascus CRK
- MEDIUM: Arno Bernard standard (Rinkhals/iMamba/Turaco), Demko AD20.5, all other collabs, recurring scheduled drops
- BASELINE events capped at HIGH maximum

---

## KNOWN GOOD STATE — 2026-03-07

### Alert counts (clean baseline)
- Total: ~25 (deduplicated)
- CRITICAL: 0 (no false positives)
- HIGH: ~12
- MEDIUM: ~13

### generate_alerts.py — key behavior
- Dedup: ONE entry per source across full 48h window (best priority wins)
- Reddit: deduped per-hour (different posts are distinct)
- Notable items merged across duplicate entries
- Sort: priority groups (critical → high → medium), newest-first within each group
- Location: /home/shg/drop-watcher/generate_alerts.py

### ai_interpreter.py — current priority rules
CRITICAL:
  - Hinderer x Steel Flame collab
  - CRK x Wilson Combat collab
  - Strider x Steel Flame collab
  - MSC (Mick Strider Custom) available for purchase — Add to cart only, not Read more

HIGH:
  - Hinderer with wood/walnut/brass/copper handles
  - CRK specials/drops (non-WC collab)
  - McNees drop banner
  - Damascus on any CRK
  - DLT Exclusive Hinderer variants

MEDIUM:
  - Arno Bernard standard models (Rinkhals, iMamba, Turaco) — no damascus
  - Demko AD20.5 (common production knife)
  - All collabs not listed above
  - Recurring scheduled drops (every Thursday, daily at X, weekday drops)

NEVER:
  - Sold-out items in notable_items
  - BASELINE events at CRITICAL (capped at HIGH)

### web_watcher.py — key behavior
- Item dedup: seen_items.json (DEDUP_HOURS window)
- Content dedup: seen_content.json (4hr suppression)
- BASELINE events capped at HIGH
- Location: /home/shg/drop-watcher/agents/web_watcher.py

### Infrastructure
- Daemon: supervisord → web_watcher.py
- Cron: */2 generate_alerts, */15 feed_watcher, */30 alerter, 7am morning_briefer, 0 3 * * 0 backup
- Backup: ~/backups/, weekly, keep last 7
- scp: scp 'shg@instockornot.club:~/backups/drop-watcher_*.tar.gz' ~/drop-watcher-backups/

### How to start next session
1. Run session starter command (top of this file)
2. Paste output to Claude
3. Say "continuing Drop Watcher dev"
4. Claude has Chrome extension available — say "take a look" and it will check alerts.html directly

### Session 6+7 — 2026-03-07
- generate_alerts.py dedup refined — ONE entry per source across full 48h window (best priority wins)
- backup_drop_watcher.sh fixed — sudo check, root ownership bug, crontab backup bug all resolved
- Boss list confirmed — Ubiquiti UVC-G6-180 Camera in sources.yaml, cool_list.yaml has ubiquiti/uvc-g6 keywords
- Boss email tested and confirmed working — simon@binnysoakland.com receives BCC on Ubiquiti source alerts
- Copyright headers added to all 6 key Python files — committed to GitHub (27fe293)
- AI Guild Talk deck built — 11 slides, navy/teal theme, at /mnt/user-data/outputs/ai-guild-talk.pptx
- Day 1 origin story slides built — 2 slides standalone, day1-story.pptx
- Slide 5 fixed — Week 1-4 replaced with accurate Day 1-7 real dates
- watchdog-framework product idea captured in handoff
- DROP-WATCHER-HANDOFF.md written and saved

**Pending next session:**
- Simon to proofread ai-guild-talk.pptx
- Day 2-5 origin story slides
- SMS alerts via Twilio (CRITICAL → text)
- instockornot.club/watchlist page (community-facing source list)
- Ubiquiti white version (UVC-G6-180-W) is Coming Soon — will be first real boss alert
- Urban EDC Supply 03/11 drop — CRK Sebenza 31 MagnaCut
- Urban EDC Supply 03/18 drop — TBD

### Session 8 — 2026-03-08

**What we built:**
- watchlist.html — public signup page live at instockornot.club/watchlist.html
- watcher_signup.py — Flask API (POST /api/watch) running via gunicorn/supervisord on port 5001
- per_user_alerter.py — cron */30 as shg, checks watchers.json, emails matches
- Apache proxy wired — /api/ → 127.0.0.1:5001 in default-ssl.conf (443 vhost)
- Rate limiting — max 10 signups/day, 24hr email cooldown, 50 emails/day cap
- SMS approval gate — phone collected but sms_approved=False until Simon approves
- Twilio account created — paid, number +19282498690 (928-WATCHER)
- A2P 10DLC registration pending — need LLC EIN + RA address (do when back)
- Email-to-SMS via vtext.com/vzwpix.com — bounced/delayed, not reliable
- goaccess wired to root cron hourly — stats/index.html now auto-updates
- Copyright headers on all 6 key Python files — committed to GitHub
- All new files committed: watcher_signup.py, per_user_alerter.py (commit 2db8138)
- hostname set to ironman via hostnamectl

**Known issues:**
- ironman can't reach southernedgeknives.com — DNS/network issue, investigate
- Gmail spam-folders per_user_alerter emails — new domain reputation, will improve
- Resend domain instockornot.club is Verified — SPF/DKIM already set

**Pending next session:**
- Twilio A2P 10DLC — complete Brand + Campaign registration (need LLC docs)
- Wire Twilio send_sms into alerter.py once A2P approved
- Confirmation email to user on signup (watcher_signup.py)
- /my-watches page — magic link, view/manage active watches
- southernedgeknives.com fetch failure — debug ironman network
- Urban EDC Supply 03/11 — CRK Sebenza 31 MagnaCut dropping
- Urban EDC Supply 03/18 — second drop TBD
- Bloomberg terminal integration 😄
### Session 8 addendum — 2026-03-08
- watchlist.html password protected — Basic Auth via /var/www/html/.htaccess
- htpasswd file at /etc/apache2/.htpasswd, username: dropwatcher
- AllowOverride All confirmed in default-ssl.conf
- Tested in incognito — prompts for credentials ✅
- Committed to GitHub (3271e02)

### Session 9 — 2026-03-09

**What we did:**
- System intentionally shut down before Montana trip
- supervisord stopped: web_watcher STOPPED, watcher_signup STOPPED
- shg crontab: all lines commented out (##)
- root crontab: goaccess and per_user_alerter commented out
- ALERT_TO_FRIENDS commented out in .env — friends alerts silenced
- .htaccess fixed — scoped to watchlist.html only via <Files> wrapper
- Tested on mobile incognito — password prompt confirmed working
- Twilio A2P 10DLC still pending — need LLC EIN + RA address
- Hostname ironman confirmed working

**To restart on return:**
1. sudo supervisorctl start all
2. crontab -e — remove # from all lines
3. sudo crontab -e — remove # from all lines
4. Verify: sudo supervisorctl status

**GitHub:** 74cbccf — last clean commit
### Session 10 — 2026-03-13

**What we did:**
- A2P 10DLC campaign completed — pending carrier vetting (CM9512a8edb874e3b0865f3e19d60daeb1)
- sms_alerter.py built — CRITICAL only, sms_approved watchers, per-alert dedup, fails silently
- alerter.py cleaned — boss/friends dropped, SMS wired in, legacy BCC removed
- README rewritten — platform mission, architecture, stack
- Platform direction confirmed — public URL/keyword alert platform

**Pending:**
- Confirmation email on signup (watcher_signup.py)
- Unsubscribe mechanism — token-based, one-click
- User-facing URL/keyword entry UI
- UptimeRobot infra monitoring

### Session 11 — 2026-03-13

**What we fixed:**
- my-alerts.html showing unrelated drops — `/api/my-alerts` was matching too broadly
  - Keywords now split on commas only (multi-word keywords like "in stock" stay intact)
  - Domain match required — drops from unrelated sites excluded
  - 3-day cutoff added — old drops filtered out
- FROM_ADDRESS changed from noreply@ to info@instockornot.club in watcher_signup.py

**Active bugs:**
- BUG-005: User who signs up but doesn't receive verification email cannot re-sign up — duplicate check blocks them, resend may not fire. Investigate and test next session.

**Pending:**
- Test BUG-005 — sign up flow when verification email fails/missing
- ~~Favicon for instockornot.club~~ DONE
- ~~Live pulse — /api/stats + watcher_status.html~~ DONE
- ~~Security cleanup — XSS, SSRF, CORS, rate limiting, input validation, file locking~~ DONE
- Server hardening — separate code/config/data dirs, file permissions, move PII out of ~/drop-watcher
- DMARC setup for instockornot.club
- UptimeRobot infra monitoring
- Discord webhook — CRITICAL drops auto-post to a Discord channel
- Easter egg /hgr page — the build story across sessions
- Browser sound alert — alerts.html plays a ping on new CRITICAL
- Redesign index.html — reflect public platform direction without losing the original aesthetic
