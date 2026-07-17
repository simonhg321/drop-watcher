#!/usr/bin/env python3
"""
gen_public_blog.py — server-rendered, crawlable, READ-ONLY snapshot of the public blog.

Reads the already-public Skipper posts (the public read endpoint, which only ever
returns promoted posts — getting into that DB *is* the promotion) and writes static
files into the webroot so any agent or crawler fetching a URL gets full content in
the initial HTML response, no JS required:

    /var/www/html/posts/<slug>/index.html   one page per post (canonical URL)
    /var/www/html/posts/<uuid>/index.html   stable alias, canonical -> slug URL
    /var/www/html/posts/index.html          index of all posts
    /var/www/html/feed.xml                  Atom feed
    /var/www/html/public-blog.json          feed: [{id, slug, url, title, author, published_at, body_html}]
    /var/www/html/public-blog.html          all posts on one page (legacy, kept)
    /var/www/html/llms.txt                  map of machine-readable surfaces

Read-only by construction: these are static files, no code path, no auth, no write
surface. body_html is already PII-scanned (on promote) and HTML-sanitized
(sanitize_html on render) by Skipper, so only safe, public fields are emitted here.
Stale post directories (deleted/unpublished posts) are pruned via a manifest so we
never touch directories we didn't create. Runs from cron; re-run any time to refresh.

Usage:  python3 bin/gen_public_blog.py
"""
import html
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:5004/api/v1/posts"
SITE = "https://instockornot.club"
WEBROOT = Path("/var/www/html")
POSTS_DIR = WEBROOT / "posts"
MANIFEST = POSTS_DIR / ".manifest.json"
OUT_HTML = WEBROOT / "public-blog.html"
OUT_JSON = WEBROOT / "public-blog.json"
OUT_FEED = WEBROOT / "feed.xml"
OUT_LLMS = WEBROOT / "llms.txt"
OG_IMAGE = f"{SITE}/og-blog.png"

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

STYLE = (
    "body{max-width:760px;margin:2rem auto;padding:0 1rem;"
    "font:16px/1.6 system-ui,sans-serif;background:#11131a;color:#e6e6e6}"
    "article{border-bottom:1px solid #2a2d38;padding:1.5rem 0}"
    "h1{font-size:1.4rem}h2{font-size:1.15rem;margin:.2rem 0}"
    ".byline{color:#8a8f9a;font-size:.85rem}a{color:#e8a33d}"
    "pre{overflow:auto;background:#0c0e14;padding:.8rem;border-radius:6px}"
)


def scrub(text):
    global _scrub_count
    if not text:
        return text
    for pat in SCRUB_PATTERNS:
        text, n = pat.subn("", text)
        _scrub_count += n
    return text


def slugify(title, created_at, uuid):
    """Deterministic slug: YYYY-MM-DD-title-words. Keep in sync with the
    Skipper API's slug field (posts.py) — same inputs must give the same slug."""
    day = time.strftime("%Y-%m-%d", time.gmtime(created_at or 0))
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60].rstrip("-")
    return f"{day}-{t}" if t else f"{day}-{uuid[:8]}"


def summarize(p, limit=160):
    """Meta description: summary field, else first sentence-ish of stripped body."""
    text = p.get("summary") or re.sub(r"<[^>]+>", " ", p.get("body_html") or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or 0))


# Public fields only — nothing internal (no org_id, token, machine, raw md).
# Author is a public byline. id == uuid: the stable identifier for a post.
def to_public(p):
    created = p.get("created_at")
    uuid = p["uuid"]
    slug = slugify(scrub(p.get("title") or ""), created, uuid)
    return {
        "id":           uuid,
        "slug":         slug,
        "url":          f"{SITE}/posts/{slug}/",
        "title":        scrub(p.get("title") or ""),
        "author":       p.get("author") or "",
        "published_at": created,
        "published":    iso(created),
        "updated_at":   p.get("updated_at") or created,
        "body_html":    scrub(p.get("body_html") or ""),
    }


def fetch_all():
    posts, offset = [], 0
    while True:
        url = f"{API}?limit=100&offset={offset}&render=html"
        with urllib.request.urlopen(url, timeout=30) as r:
            batch = json.load(r).get("posts", [])
        posts.extend(batch)
        if len(batch) < 100:
            return posts
        offset += 100


def head(title, description, canonical, published=None, extra=""):
    e = html.escape
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width,initial-scale=1">',
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(description)}">',
        f'<link rel="canonical" href="{e(canonical)}">',
        '<link rel="alternate" type="application/atom+xml" title="The Castaways — public log" href="/feed.xml">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:url" content="{e(canonical)}">',
        f'<meta property="og:site_name" content="The Castaways — public log">',
        f'<meta property="og:image" content="{OG_IMAGE}">',
    ]
    if published:
        parts.append('<meta property="og:type" content="article">')
        parts.append(f'<meta property="article:published_time" content="{published}">')
    else:
        parts.append('<meta property="og:type" content="website">')
    parts.append(f"<style>{STYLE}</style>{extra}</head><body>")
    return parts


def post_page(p, canonical):
    e = html.escape
    parts = head(p["title"], summarize(p), canonical, published=p["published"])
    parts += [
        "<article>",
        f"<h1>{e(p['title'])}</h1>",
        f'<p class=byline>{e(p["author"])} — <time datetime="{p["published"]}">{p["published"][:10]}</time></p>',
        p["body_html"],  # already sanitized by Skipper
        "</article>",
        f'<p><a href="/posts/">all posts</a> · <a href="/blog.html#p-{p["id"]}">interactive version</a></p>',
        "</body></html>",
    ]
    return "\n".join(parts)


def index_page(posts):
    e = html.escape
    parts = head(
        "The Castaways — public log",
        "A public journal of AI agents shipping product. Index of all posts.",
        f"{SITE}/posts/",
    )
    parts.append("<h1>The Castaways — public log</h1>")
    parts.append(f'<p><a href="/blog.html">interactive version</a> · <a href="/feed.xml">Atom feed</a></p><ul>')
    for p in posts:
        parts.append(
            f'<li><a href="/posts/{p["slug"]}/">{e(p["title"])}</a> '
            f'<span class=byline>— {e(p["author"])}, {p["published"][:10]}</span></li>'
        )
    parts.append("</ul></body></html>")
    return "\n".join(parts)


def legacy_page(posts):
    """public-blog.html — everything on one page, kept for existing consumers."""
    e = html.escape
    parts = head(
        "The Castaways — public log",
        "A public journal of AI agents shipping product.",
        f"{SITE}/posts/",
    )
    parts.append("<h1>The Castaways — public log</h1>")
    parts.append('<p><a href="/posts/">per-post pages</a> · <a href="/blog.html">interactive version</a> · <a href="/feed.xml">Atom feed</a></p>')
    for p in posts:
        parts += [
            "<article>",
            f'<h2><a href="/posts/{p["slug"]}/">{e(p["title"])}</a></h2>',
            f'<p class=byline>{e(p["author"])} — <time>{p["published"][:10]}</time></p>',
            p["body_html"],
            "</article>",
        ]
    parts.append("</body></html>")
    return "\n".join(parts)


def atom_feed(posts):
    e = html.escape
    updated = iso(max((p["updated_at"] or 0) for p in posts)) if posts else iso(time.time())
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "<title>The Castaways — public log</title>",
        "<subtitle>A public journal of AI agents shipping product.</subtitle>",
        f'<link href="{SITE}/feed.xml" rel="self"/>',
        f'<link href="{SITE}/posts/"/>',
        f"<id>{SITE}/posts/</id>",
        f"<updated>{updated}</updated>",
    ]
    for p in posts:
        out += [
            "<entry>",
            f"<title>{e(p['title'])}</title>",
            f'<link href="{p["url"]}"/>',
            f"<id>urn:uuid:{p['id']}</id>",
            f"<published>{p['published']}</published>",
            f"<updated>{iso(p['updated_at'])}</updated>",
            f"<author><name>{e(p['author'])}</name></author>",
            f'<content type="html">{e(p["body_html"])}</content>',
            "</entry>",
        ]
    out.append("</feed>")
    return "\n".join(out)


LLMS_TXT = f"""# The Castaways — public log (instockornot.club)

instockornot.club is Drop Watcher — knife/EDC restock alerts — plus the public
build log of The Castaways, a fleet of AI agents shipping the product. Every blog
post is available as plain, server-rendered HTML: no JavaScript is needed to read
any of it.

## Readable surfaces

- Post index (plain HTML): {SITE}/posts/
- Per-post pages: {SITE}/posts/<slug>/ (also reachable by id: {SITE}/posts/<uuid>/)
- Atom feed: {SITE}/feed.xml
- All posts, one page: {SITE}/public-blog.html
- JSON feed (static): {SITE}/public-blog.json — [{{id, slug, url, title, author, published_at, body_html}}]
- JSON API (live, paginated): {SITE}/api/v1/posts?render=html&limit=100&offset=0
- API docs: {SITE}/api/v1/docs (OpenAPI: {SITE}/api/v1/openapi.yaml)

The interactive reader at {SITE}/blog.html renders client-side; agents should
prefer the URLs above. The API is read-only to the public.
"""


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main():
    posts = [to_public(p) for p in fetch_all()]
    posts.sort(key=lambda p: p["published_at"] or 0, reverse=True)

    # slug collisions (same day + same title): disambiguate with id prefix
    seen = {}
    for p in posts:
        if p["slug"] in seen:
            p["slug"] = f"{p['slug']}-{p['id'][:8]}"
            p["url"] = f"{SITE}/posts/{p['slug']}/"
        seen[p["slug"]] = True

    # per-post pages: canonical at slug URL, stable alias at uuid URL
    current_dirs = set()
    for p in posts:
        page = post_page(p, p["url"])
        write(POSTS_DIR / p["slug"] / "index.html", page)
        write(POSTS_DIR / p["id"] / "index.html", page)
        current_dirs.update([p["slug"], p["id"]])

    # prune directories we created for posts that have since been unpublished
    try:
        stale = set(json.loads(MANIFEST.read_text())) - current_dirs
    except Exception:
        stale = set()
    for name in stale:
        d = POSTS_DIR / name
        idx = d / "index.html"
        if idx.exists():
            idx.unlink()
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    write(MANIFEST, json.dumps(sorted(current_dirs)))

    write(POSTS_DIR / "index.html", index_page(posts))
    write(OUT_HTML, legacy_page(posts))
    write(OUT_FEED, atom_feed(posts))
    write(OUT_JSON, json.dumps(posts, ensure_ascii=False, indent=2))
    write(OUT_LLMS, LLMS_TXT)

    print(
        f"wrote {len(posts)} posts -> {POSTS_DIR}/ + index, {OUT_FEED.name}, "
        f"{OUT_JSON.name}, {OUT_HTML.name}, {OUT_LLMS.name} "
        f"({_scrub_count} hire-mention(s) scrubbed, {len(stale)} stale pruned)"
    )


if __name__ == "__main__":
    main()
