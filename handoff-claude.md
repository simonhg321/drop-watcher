# Drop Watcher — Project Briefing

## What it is
Drop Watcher (instockornot.club) is a free alert service that watches any webpage for keywords you care about. You give it a URL and your keywords, it checks the page every 10-30 minutes, and emails you the moment your keywords appear.

## Origin story
Built by Simon (HGR) — a knife and EDC gear collector who got tired of missing limited drops that sell out in seconds. Started as a personal tool to track Steel Flame jewelry and mid-tech knife drops. Now it's open to anyone watching for anything.

## How it works
1. You paste a URL and your keywords (e.g., "Damascus, skeleton, chris reeve")
2. Verify your email — one click
3. The system watches around the clock
4. When your keywords show up on the page, you get an email with a direct link

## Tech (for context, not for the post)
- Python, Claude AI for intelligent page analysis, runs on a single Linode server
- AI distinguishes between routine restocks (medium priority) and genuinely rare drops (critical)
- Monitors 40+ knife dealer and maker sites plus Reddit feeds
- Built in 14 days, mostly pair-programmed with Claude Code
- Self-healing — watchdog restarts anything that dies

## The vibe
- Built for collectors, not bots or resellers
- Polite scraping — never hammers sites
- No account needed — just URL + keywords + email
- Free, no ads, no data selling
- The system watches. Every purchase decision belongs to the human.

## Milestone
Just caught its first real drop in the wild — Strider knives dropped and the system detected it and fired an alert. SMS alerts coming next week so drops that sell out in minutes don't get missed.

## Who uses it
Right now it's knife/EDC collectors but it works for anything — sneaker drops, camera restocks, limited merch, concert tickets, anything on a webpage.

## Ask
Help me write a Facebook post announcing this to my friends and the knife/EDC community. Casual, authentic, not corporate. I sign off as HGR.
