#!/usr/bin/env python3
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
smoke_structured_linking.py — live, READ-ONLY smoke test for the structured
item->link resolution chain (S55).

It fetches a handful of REAL dealer pages over plain HTTP GET (exactly what the
scraper already does) and checks that fetch_collection now resolves them to
STRUCTURED products with deep-link URLs instead of a bare homepage:

  • Shopify dealers configured with a homepage URL  -> tier 1 (root products.json)
  • non-Shopify server-rendered dealers              -> tier 3 (product cards)

For each dealer it prints what a user's alert email would actually link to, and
asserts the resolved product URLs are same-site deep links (never the bare
homepage, never cross-site). Network flakiness -> SKIP (not FAIL); a reachable
page that yields neither structured products NOR fuzzy candidates -> FAIL (that
is the regression we are guarding against).

Run from anywhere; re-runnable against the production checkout after merge.
Exit code 0 = all reachable dealers passed; 1 = at least one FAIL.
"""
import os
import sys
import urllib.request
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

import collection_fetch  # noqa: E402
from linkpick import same_site  # noqa: E402

# Representative real dealers. 'kind' documents which tier we EXPECT to fire.
DEALERS = [
    {"name": "Southern Edges", "url": "https://southernedges.com",        "kind": "shopify-root"},
    {"name": "Urban EDC Supply", "url": "https://urbanedcsupply.com",      "kind": "shopify-root"},
    {"name": "Hog House Knives", "url": "https://hoghouseknives.com",       "kind": "shopify-root"},
    {"name": "Lamnia",          "url": "https://www.lamnia.com/en/",        "kind": "cards"},
    {"name": "eKnives Pre-Owned","url": "https://eknives.com/preowned/",    "kind": "cards-or-candidates"},
]

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch_page(url, ssl_permissive=False):
    """READ-ONLY GET returning str|None — mirrors web_watcher.fetch_page loosely."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read(2_000_000).decode("utf-8", "ignore")
    except Exception:
        return None


def _is_deep_link(url, base_url):
    """A real product link: same-site AND a path with a non-trivial segment
    (i.e. not the bare homepage '/' )."""
    if not url or not same_site(urlparse(url).hostname, urlparse(base_url).hostname):
        return False
    path = urlparse(url).path.strip("/")
    return len(path) >= 4


def check_dealer(d):
    """Returns (status, detail) where status in {'PASS','FAIL','SKIP'}."""
    base = d["url"]
    # Reachability probe first so a down site is SKIP, not FAIL.
    if fetch_page(base) is None:
        return "SKIP", "unreachable (network/site down)"

    text, products, candidates = collection_fetch.fetch_collection(base, fetch_page)

    if products:
        deep = [p for p in products if _is_deep_link(p.get("url", ""), base)]
        cross = [p for p in products
                 if p.get("url") and not same_site(
                     urlparse(p["url"]).hostname, urlparse(base).hostname)]
        if cross:
            return "FAIL", f"{len(cross)} CROSS-SITE product url(s) — e.g. {cross[0]['url']}"
        if not deep:
            return "FAIL", f"{len(products)} products but none are deep links (homepage-only?)"
        sample = deep[:3]
        lines = [f"{len(products)} structured products; {len(deep)} deep-linked. Samples:"]
        for p in sample:
            avail = "in-stock" if p.get("available") else "sold-out"
            price = f"${p['price']}" if p.get("price") else "-"
            lines.append(f"      • {p['title'][:48]:48}  {price:>10}  {avail}")
            lines.append(f"        -> {p['url']}")
        return "PASS", "\n".join(lines)

    # No structured products. Candidates are an acceptable fallback ONLY for the
    # 'cards-or-candidates' kind; a homepage that yields NOTHING is the regression.
    if candidates:
        if d["kind"] in ("cards-or-candidates",):
            return "PASS", f"no structured products; {len(candidates)} fuzzy candidates (acceptable fallback)"
        return "FAIL", (f"expected structured products ({d['kind']}) but got only "
                        f"{len(candidates)} fuzzy candidates — tier missed")
    return "FAIL", "reachable but 0 structured products AND 0 candidates (bare-homepage regression)"


def main():
    print("=" * 72)
    print("SMOKE: structured item->link resolution (S55) — live, read-only")
    print("=" * 72)
    results = []
    for d in DEALERS:
        status, detail = check_dealer(d)
        results.append((status, d))
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚠️ "}[status]
        print(f"\n{mark} {status}  {d['name']}  ({d['kind']})  {d['url']}")
        for ln in detail.splitlines():
            print(f"    {ln}")

    fails = [d for s, d in results if s == "FAIL"]
    skips = [d for s, d in results if s == "SKIP"]
    passes = [d for s, d in results if s == "PASS"]
    print("\n" + "=" * 72)
    print(f"RESULT: {len(passes)} PASS, {len(fails)} FAIL, {len(skips)} SKIP "
          f"(of {len(DEALERS)} dealers)")
    if skips:
        print("  SKIPPED (unreachable, not a failure): " + ", ".join(d["name"] for d in skips))
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
