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
- Built with AI, open source — fork it, learn how AI and humans build software together

---

## Core Values

- **Good citizen** — polite polling, randomized intervals, respectful rate limits. No hammering small sites.
- **Collector-first, dealer-friendly** — every alert deep-links to the seller's own product page. We deliver a buyer with intent at the moment of restock, and we charge dealers nothing.
- **No automated purchasing — ever** — the system watches and alerts. A human pulls the trigger.
- **Transparent** — we monitor from one fixed address and will identify with any User-Agent string a site asks for, and the full list of makers and dealers we watch is public: [what-we-watch](https://instockornot.club/what-we-watch.html).
- **Opt-out honored** — any site that wants out of monitoring says so once and we drop it. We never work around a block.
- **ELv2 licensed** — free for personal use, closed to commercial exploitation

---

## For Dealers

If you sell knives and found this page because our monitor showed up in your logs: Drop Watcher is a funnel **to** you, not a leech. Collectors tell us exactly which models they're hunting; when one appears in stock on your site, we email them a link straight to your product page. Read-only checks, a few times an hour, roughly one extra shopper's worth of load — and the sale happens on your site, from your cart.

Blocking us doesn't stop bots; it just sends that buyer to whichever of your competitors we *can* see. Want to be allowlisted, point us at a feed, or opt out entirely? One email: [simon@instockornot.club](mailto:simon@instockornot.club).

---

## Architecture

```
supervisord
├── web_watcher.py       — polls maker/dealer sites, structured product extraction
├── watcher_signup.py    — Flask API for public watcher registration (gunicorn)
└── onboarding-sse       — Go microservice, live signup progress

cron
├── */2   generate_alerts.py   — builds live alerts page
├── */2   watchdog.py          — pipeline health, silent-failure detection
├── */10  per_user_alerter.py  — per-watcher keyword matching → email/SMS
├── */15  feed_watcher.py      — Reddit RSS (r/bladesinstock, r/knife_swap, r/crk)
├── */30  drops.mon            — canary monitor: 6 known-good matches must fire
├── 6:20  dealer_scout.py      — auto-discovers new dealers from user watches
├── 7am   morning_briefer.py   — daily summary
└── 0 3 * * 0  backup          — weekly backup, keep last 7
```

Plus a 126-dealer registry (`config/dealer_registry.yaml`) — every legit knife
dealer we know of, vetted, statused and growing!

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

**Simon Gibson (HGR)** is currently pursuing the **[GIAC Strategic Planning, Policy, and Leadership (GSTRT)](https://www.giac.org/certifications/strategic-planning-policy-leadership-gstrt/)** certification — cyber security program strategy, policy, and executive leadership.

---

*Built across 60 sessions with Claude (Anthropic) as co-pilot — architecture, debugging, and the occasional argument about git stashes. Claude did half. I did the half that mattered.*

**SGH**
