# Drop Watcher
### instockornot.club

A public alert platform for knife and EDC collectors. Enter a URL and keywords — get notified when drops happen.

---

## Mission

The knife and EDC collector world moves fast. Limited runs sell out in minutes. Steel Flame drops are announced and gone before most people see them. Drop Watcher exists to level the playing field for collectors — not dealers, not bots, not resellers.

You enter what you're watching for. The system watches. You get alerted. You decide.

---

## What It Does

- Monitors maker and dealer sites for inventory changes and drop announcements
- Scores alerts by priority — CRITICAL for rare collabs and customs, HIGH for specials, MEDIUM for production runs
- Sends email and SMS alerts to registered watchers when something worth caring about surfaces
- Runs a live public alert feed at [instockornot.club/alerts.html](https://instockornot.club/alerts.html)

---

## Core Values

- **Good citizen** — polite polling, randomized intervals, respectful rate limits. No hammering small maker sites.
- **Collector-first** — built for the community, not dealers or resellers
- **No automated purchasing** — the system watches and alerts, you pull the trigger
- **ELv2 licensed** — free for collectors, closed to commercial exploitation

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
- Apache + SSL (Let's Encrypt)
- Resend (email delivery)
- Twilio A2P 10DLC (SMS)
- supervisord + cron
- GitHub: simonhg321/drop-watcher

---

## License

ELv2 — see [LICENSE](LICENSE). Free for personal and community use. Commercial use by dealers or retailers is explicitly prohibited.

---

*Built session by session with Claude (Anthropic) as co-pilot — architecture, debugging, and the occasional argument about the right way to do things.*

**HGR**
