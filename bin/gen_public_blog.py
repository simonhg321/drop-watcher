#!/usr/bin/env python3
"""
gen_public_blog.py — server-rendered, crawlable, READ-ONLY snapshot of the public blog.

Reads the already-public Skipper posts (the public read endpoint, which only ever
returns promoted posts — getting into that DB *is* the promotion) and writes two
static files into the webroot:

    /var/www/html/public-blog.html   full content baked into the initial response (crawlable, no JS)
    /var/www/html/public-blog.json   minimal feed: [{slug, title, published_at, body_html}]

Read-only by construction: these are static files, no code path, no auth, no write surface.
body_html is already PII-scanned (on promote) and HTML-sanitized (sanitize_html on render)
by Skipper, so only safe, public fields are emitted here. Re-run to refresh after a promote.

Usage:  python3 bin/gen_public_blog.py
"""
import html
import json
import re
import time
import urllib.request

SRC = "http://127.0.0.1:5004/api/v1/posts?limit=200&render=html"
OUT_HTML = "/var/www/html/public-blog.html"
OUT_JSON = "/var/www/html/public-blog.json"

# --- scrub: remove hire-context Anthropic mentions before anything goes crawlable. ---
# Hire-context ONLY — deliberately leaves benign technical mentions intact
# ("Anthropic API rate limit", "anthropic.token", the Mythos paper, noreply@anthropic.com).
# Add patterns here if more sensitive phrasings surface.
SCRUB_PATTERNS = [
    re.compile(r"(?i)\bapplying to anthropic\b[^.<]*\.?\s*"),
    re.compile(r"(?i)\b(trying|hoping|wanting|looking)\s+to\s+get\s+(hired|a job)\s+(at|by|with)\s+anthropic\b[^.<]*\.?\s*"),
    re.compile(r"(?i)\b(applied|interview(?:ed|ing)?|recruited|recruiting)\s+(at|by|with|for|to)\s+anthropic\b[^.<]*\.?\s*"),
    re.compile(r"(?i)\bhire\s+me\b[^.<]*\banthropic\b[^.<]*\.?\s*"),
]

_scrub_count = 0


def scrub(text):
    global _scrub_count
    if not text:
        return text
    for pat in SCRUB_PATTERNS:
        text, n = pat.subn("", text)
        _scrub_count += n
    return text


# Public fields only — nothing internal (no org_id, token, machine, raw md).
def to_public(p):
    return {
        "slug":         p["uuid"],
        "title":        scrub(p.get("title") or ""),
        "published_at": p.get("created_at"),
        "body_html":    scrub(p.get("body_html") or ""),
    }


def main():
    with urllib.request.urlopen(SRC, timeout=30) as r:
        data = json.load(r)
    posts = [to_public(p) for p in data.get("posts", [])]

    # --- feed.json ---
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    # --- server-rendered HTML (content present in the initial response) ---
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width,initial-scale=1">',
        "<title>The Castaways — public log</title>",
        '<meta name=description content="A public journal of AI agents shipping product.">',
        "<style>body{max-width:760px;margin:2rem auto;padding:0 1rem;"
        "font:16px/1.6 system-ui,sans-serif;background:#11131a;color:#e6e6e6}"
        "article{border-bottom:1px solid #2a2d38;padding:1.5rem 0}"
        "h1{font-size:1.4rem}h2{font-size:1.15rem;margin:.2rem 0}"
        "time{color:#8a8f9a;font-size:.85rem}a{color:#e8a33d}"
        "pre{overflow:auto;background:#0c0e14;padding:.8rem;border-radius:6px}</style>",
        "</head><body>",
        "<h1>The Castaways — public log</h1>",
        '<p><a href="/blog.html">interactive version</a></p>',
    ]
    for p in posts:
        ts = p["published_at"]
        when = time.strftime("%Y-%m-%d", time.gmtime(ts)) if isinstance(ts, (int, float)) else ""
        parts.append("<article>")
        parts.append(f"<h2>{html.escape(p['title'])}</h2>")
        if when:
            parts.append(f"<time>{when}</time>")
        parts.append(p["body_html"])  # already sanitized by Skipper
        parts.append("</article>")
    parts.append("</body></html>")

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    print(f"wrote {len(posts)} posts -> {OUT_HTML} + {OUT_JSON} ({_scrub_count} hire-mention(s) scrubbed)")


if __name__ == "__main__":
    main()
