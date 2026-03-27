# Drop Watcher
### instockornot.club

A public alert platform for collectors. Enter a URL and keywords — get notified when drops happen.

---

## Mission

If you're looking for something — knives, sneakers, GPUs, cameras, limited releases, anything — Drop Watcher watches the page so you don't have to. Enter a URL and your keywords. Walk away. Get an email when it hits, and a text so you know to check it.

Built for collectors. Works on anything.

---

## What It Does

- Monitors any URL for inventory changes and drop announcements
- AI-powered page analysis — knows the difference between "add to cart" and "sold out"
- Scores alerts by priority — CRITICAL for rare finds, HIGH for specials, MEDIUM for production runs
- Email alerts with full details + SMS nudge so you never miss the email
- Live public alert feed at [instockornot.club](https://instockornot.club/)
- Free. No account. No app. No password.

---

## Core Values

- **Good citizen** — polite polling, randomized intervals, respectful rate limits. No hammering small sites.
- **Collector-first** — built for people who want things, not dealers or resellers
- **No automated purchasing** — the system watches and alerts, you pull the trigger
- **ELv2 licensed** — free for personal use, closed to commercial exploitation

---

## Architecture

```
supervisord
├── web_watcher.py       — polls maker/dealer sites, detects changes
└── watcher_signup.py    — Flask API for public watcher registration

cron
├── */2   generate_alerts.py   — builds live alerts page
├── */15  feed_watcher.py      — Reddit RSS (r/bladesinstock, r/knife_swap)
├── */30  alerter.py           — email + SMS for CRITICAL/HIGH alerts
├── */30  per_user_alerter.py  — per-watcher keyword matching
├── 7am   morning_briefer.py   — daily summary
└── 0 3 * * 0  backup          — weekly backup, keep last 7
```

---

## Stack

- Python 3 / Ubuntu 22.04 (Linode)
- Go (onboarding SSE microservice)
- Apache + SSL (Let's Encrypt)
- Cloudflare (CDN, analytics, DDoS)
- Claude Haiku (AI page analysis, drop detection)
- Resend (email delivery)
- Twilio A2P 10DLC (SMS)
- Discord webhook (drop notifications)
- supervisord + cron
- GitHub: simonhg321/drop-watcher

---

## License

ELv2 — see [LICENSE](LICENSE). Free for personal and community use. Commercial use by dealers or retailers is explicitly prohibited.

---

*Built across 23 sessions with Claude (Anthropic) as co-pilot — architecture, debugging, and the occasional argument about git stashes. Claude did half. I did the half that mattered.*

**SGH**
