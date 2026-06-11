# Drop Watcher — Known Bugs

## BUG-011: Stale HTML served — iPad showed old watchlist.html (no Cache-Control)
**Logged:** 2026-06-10 (reported by Simon, S59) — root-caused same day
**Severity:** Medium (users see outdated pages; URL looks correct)
**Description:** Originally reported as "BladeShow content not loading on watcher
page." Actual repro: the WHERE TO WATCH cards on `watchlist.html` showed the OLD
page version (missing ALL OUR SHOPS) on Simon's iPad the night of Jun 9-10, with
the correct URL.
**Root cause:** Our HTML responses send `Last-Modified` but **no `Cache-Control`
header** (confirmed via curl; Cloudflare is `cf-cache-status: DYNAMIC`, so it's not
server-side). Per RFC heuristic caching, Safari reuses the cached copy without
revalidating — and `watchlist.html` had been updated at 01:26 that night, so any
iPad that had visited before then kept the stale copy.
**Fix:** `bin/fix_html_cache.sh` — adds an Apache conf
(`conf-available/html-nocache.conf`) setting `Cache-Control: no-cache,
must-revalidate` on `*.html` only (assets still cache). Unchanged pages revalidate
to a cheap 304. Run with sudo; script verifies the live header after reload.
**Status:** RESOLVED 2026-06-11 — Simon ran the script; `cache-control: no-cache,
must-revalidate` verified on live responses. HTML now revalidates everywhere.

## BUG-007: Stale web/ directory in repo
**Logged:** 2026-03-14
**Severity:** Low (no user impact yet, but a landmine)
**Description:** `web/html/` contains old copies of HTML files including `.bak` files. These are not served but could cause confusion about which version is canonical. The real webroot is `/var/www/html/` on ironman.
**Fix:** Delete `web/` directory from repo and ironman. Ensure ship alias only copies from project root.

## BUG-008: orchestrator.py is an empty file
**Logged:** 2026-03-14
**Severity:** Trivial
**Description:** `orchestrator.py` is a 1-line empty file. Nothing imports it. Likely a placeholder from early development.
**Fix:** Delete it.

## BUG-009: Alert/digest emails can't deep-link store-collection items to the product
**Logged:** 2026-06-07
**Severity:** Medium (UX — links land on a page, not the product)
**Description:** Alert and backfill-digest emails deep-link to a specific product only when
the drop carries a structured `products[]` list with per-item URLs. As of 2026-06-07 only
~39 of 632 drops (7 days) had non-empty `products[]`. For Reddit/feed drops this is moot —
the drop `url`/`entry_url` already IS the listing, so those land on the product. But for
**Shopify/store collection scrapes** (e.g. Knife Art, EDC Lifestyle, Edgeworks) the scraper
captures the product *name* into `notable_items` text but **never captures the product
`href`**, so the email can only link to the scraped page (collection/homepage). Knife Art is
worst — its drop `url` is the bare homepage.
**Why not fabricate `/search?q=<title>`:** verified unreliable — Edgeworks (Shopify) returns
200 but EDC Lifestyle and Knife Art return 404 (different search paths). A dead link is worse
than a working page, so `backfill_alerter.digest_items` deliberately links the real scraped
page for store items and shows name + price as the signal. See `_item_link` / `digest_items`.
**Real fix:** enhance the collection scraper (agents/) to capture each product's `href` (with
price + availability) into `products[]` at scrape time. Then `select_matched_products` yields
real product URLs and every store item deep-links to the actual product, for all future drops.
Existing corpus can't be backfilled (URLs were never stored).
**Workaround in place:** reliable-links-only — real product URLs + Reddit/feed post URLs land
on the item; store-collection items show exact name+price linked to the scraped page.
**UPDATE 2026-06-07:** linkpick ported from Billboard (stark). `collection_fetch` now harvests
product anchors into `link_candidates`; `per_user_alerter.resolve_drop_items` resolves matched
items to real product pages (shared by live alert + backfill digest). Sold-out items are skipped
(`_is_sold_out`). Deep-linking works for Shopify + non-Shopify stores + Reddit/feed.

## BUG-010: No durable record of which emails/items we've sent → repeat alerts
**Logged:** 2026-06-07
**Severity:** Medium (user-facing — duplicate alerts erode trust)
**Description:** The only dedup is the `cooldown` table keyed on (watcher_id, drop_url, matches)
with a 6h TTL (`COOLDOWN_HOURS`). After 6h the same in-stock item can re-alert, and there is no
permanent per-(user, item) sent-log. So a watcher can receive the same product repeatedly across
days, and a manual resend (e.g. the S54 personal-note resend) has no way to know who already
received a given item. `logs/alerts_sent.jsonl` exists but is stale/unused.
**Fix:** add a durable `sent_items` table (watcher_id, item_url/key, first_sent, last_sent, count)
written on every successful alert/digest send; consult it (not just the 6h cooldown) before
sending. Lets us suppress lifetime repeats and gives resends an idempotency key.
**Interim:** the S54 personal-note resend live-verifies availability at send time and is a
deliberate one-off; it is not protected against re-running twice.
