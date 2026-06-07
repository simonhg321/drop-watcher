# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
collection_fetch.py — pagination / Shopify-aware page fetching, no browser required.

THE PROBLEM
  Many dealer storefronts (especially Shopify) server-render only the FIRST page of
  a collection (~30 products). The rest load via JavaScript infinite-scroll, which a
  plain requests+BeautifulSoup scraper never executes. Result: a keyword like
  "Damascus" that lives only on later pages (or in product tags) is invisible — the
  word isn't in the served HTML at all, so there's nothing for BeautifulSoup to find.

THE FIX (no headless browser)
  The "load more" button doesn't invent products — it issues an HTTP GET to a
  paginated URL. We replicate that GET:

  1. Shopify fast path — if the URL is a Shopify collection, pull
     /collections/<handle>/products.json?limit=250&page=N. Returns every product as
     structured data (title, vendor, tags, per-variant availability + price), so even
     tag-based filter facets like "Damascus" surface. No JS.
  2. Generic pagination walk — otherwise fetch page 1, follow <link rel="next"> /
     ?page=N links, accumulating text, up to MAX_PAGES.
  3. Single page — for a normal (non-collection) URL with no next link, behaves
     exactly like the old single fetch.

  All HTTP goes through the caller's `fetch_page(url, ssl_permissive)->str|None` so SSL
  handling, headers, timeouts and size limits stay in one place (web_watcher.fetch_page).
HGR
"""

import json
import re
import time
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

import linkpick
import product_extract

SHOPIFY_LIMIT       = 100   # keep each products.json page well under fetch_page's 2MB cap
SHOPIFY_MAX_PAGES   = 8      # up to 800 products — plenty for keyword watches
HTML_MAX_PAGES      = 4     # generic ?page=N walk cap
PAGE_SLEEP_SECONDS  = 0.8   # politeness between pages of the SAME site

_STRIP_TAGS = ['nav', 'header', 'footer', 'script', 'style', 'meta', 'link']


def _strip_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    return soup.get_text(separator=' ', strip=True)


def _candidates_from_html(html, url):
    """Product-looking anchors from a non-Shopify page, for deep-linking matched
    items later (the alerter resolves the best one per matched product). Returns []
    on any failure — candidates are a best-effort nicety, never a hard dependency."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        return linkpick.extract_candidates(soup, url)
    except Exception:
        return []


# ── Shopify ───────────────────────────────────────────────────────────────────

def shopify_products_url(url):
    """Return the products.json base for a Shopify URL, else None.

    A /collections/<handle> URL → that collection's products.json. Any other URL on
    a real host (homepage, /pages/..., a product page) → the site-root /products.json,
    which every Shopify store exposes. Caller verifies the response actually parses as
    Shopify JSON, so a root guess on a non-Shopify site simply fails downstream and the
    chain falls through to the HTML path.
    """
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return None
    m = re.match(r'(/collections/[^/?#]+)', p.path)
    if m:
        return f"{p.scheme}://{p.netloc}{m.group(1)}/products.json"
    return f"{p.scheme}://{p.netloc}/products.json"


def _parse_products(products, base_url):
    """Structured product dicts: title, vendor, url, available, tags, price.

    `url` is the canonical Shopify product page (/products/<handle>) so an alert can
    deep-link straight to the matched item instead of the whole collection.
    """
    p = urlparse(base_url)
    out = []
    for pr in products:
        handle = pr.get('handle', '')
        title  = pr.get('title', '')
        vendor = pr.get('vendor', '')
        tags   = pr.get('tags', '')
        if isinstance(tags, list):
            tags_list = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tags_list = [t.strip() for t in str(tags).split(',') if t.strip()]
        variants  = pr.get('variants', []) or []
        available = any(v.get('available') for v in variants)
        price     = variants[0].get('price', '') if variants else ''
        # No handle (3rd-party-feed items, gift-card/bundle pseudo-products) → no
        # item-level deep-link. Leave url empty so the alerter skips it and falls back
        # to the collection page link, rather than mislinking the item to the collection.
        purl      = f"{p.scheme}://{p.netloc}/products/{handle}" if handle else ''
        out.append({
            'title': title,
            'vendor': vendor,
            'url': purl,
            'available': available,
            'tags': tags_list,
            'price': price,
        })
    return out


def _product_line(pr):
    """One searchable text line per product: title, vendor, stock status, price, tags."""
    status = 'IN STOCK' if pr['available'] else 'SOLD OUT'
    tags   = ', '.join(pr['tags'])
    return f"{pr['title']} — {pr['vendor']} — {status} — ${pr['price']} — tags: {tags}"


def fetch_shopify_collection(url, fetch_page, ssl_permissive=False, log=None):
    """Return (text, products) via products.json, or (None, None) if not Shopify/failed.

    `text` is the flattened searchable blob (unchanged from before); `products` is the
    structured list from _parse_products for deep-linking matched items.
    """
    base = shopify_products_url(url)
    if not base:
        return None, None
    sep = '&' if '?' in base else '?'
    products = []
    for page in range(1, SHOPIFY_MAX_PAGES + 1):
        purl = f"{base}{sep}limit={SHOPIFY_LIMIT}&page={page}"
        raw = fetch_page(purl, ssl_permissive)
        if not raw:
            break
        try:
            data = json.loads(raw)
        except Exception:
            # Page 1 unparseable → not a usable Shopify endpoint (or fully truncated).
            # A LATER page failing (e.g. an oversized page hit the fetch cap) must not
            # throw away the products we already collected from earlier pages.
            if products:
                if log:
                    log.warning(f"[collection_fetch] page {page} unparseable for {url}; "
                                f"returning {len(products)} products from earlier pages")
                break
            return None, None
        page_products = data.get('products', [])
        if not page_products:
            break
        products.extend(_parse_products(page_products, url))
        if len(page_products) < SHOPIFY_LIMIT:
            break
        if PAGE_SLEEP_SECONDS:
            time.sleep(PAGE_SLEEP_SECONDS)
    if not products:
        return None, None
    if log:
        log.info(f"[collection_fetch] Shopify products.json — {len(products)} products for {url}")
    return '\n'.join(_product_line(pr) for pr in products), products


# ── Generic pagination walk ─────────────────────────────────────────────────

def _next_link(html, current_url):
    soup = BeautifulSoup(html, 'html.parser')
    link = soup.find('link', rel='next')
    if link and link.get('href'):
        return urljoin(current_url, link['href'])
    a = soup.find('a', attrs={'rel': 'next'})
    if a and a.get('href'):
        return urljoin(current_url, a['href'])
    return None


def fetch_paginated_html(url, fetch_page, ssl_permissive=False, log=None):
    """Fetch page 1, then follow rel=next up to HTML_MAX_PAGES. Returns
    (combined_text, candidates) — candidates are product-looking anchors harvested
    from each page's raw html (before text-stripping) for deep-linking, deduped by
    href across pages and capped. (None, []) if nothing fetched."""
    texts = []
    cand_by_href = {}
    current = url
    pages = 0
    for _ in range(HTML_MAX_PAGES):
        html = fetch_page(current, ssl_permissive)
        if not html:
            break
        nxt = _next_link(html, current)        # read before stripping <link> tags
        for c in _candidates_from_html(html, current):
            cand_by_href.setdefault(c['href'], c)   # first (highest-ranked) wins
        texts.append(_strip_text(html))
        pages += 1
        if not nxt or nxt == current:
            break
        current = nxt
        if PAGE_SLEEP_SECONDS:
            time.sleep(PAGE_SLEEP_SECONDS)
    if not texts:
        return None, []
    if log and pages > 1:
        log.info(f"[collection_fetch] paginated HTML — walked {pages} pages for {url}")
    return '\n'.join(texts), list(cand_by_href.values())[:linkpick.LINK_INDEX_MAX]


# ── Orchestrator ────────────────────────────────────────────────────────────

def fetch_collection(url, fetch_page, ssl_permissive=False, log=None, hints=None):
    """Pagination/Shopify-aware fetch. Returns (text, products, candidates).

    `products` is the structured list of {title, vendor, url, available, tags, price}
    whenever ANY structured tier resolves (Shopify products.json, JSON-LD, or product-card
    DOM extraction), else None. When products are structured, `candidates` is [] — the
    alerter deep-links from the structured list and must not fall back to fuzzy anchors.
    `candidates` is the best-effort fuzzy anchor list ONLY when no structured tier hit.
    `hints` is an optional per-store dict of CSS selectors for tier-3 extraction.
    """
    try:
        text, products = fetch_shopify_collection(
            url, fetch_page, ssl_permissive=ssl_permissive, log=log)
        if text:
            return text, products, []
    except Exception as e:
        if log:
            log.warning(f"[collection_fetch] Shopify path failed for {url}: {e}")

    # Non-Shopify: fetch page 1 ONCE and try structured extraction first (the common
    # case for our dealers). Only if nothing structured resolves do we pay for the
    # multi-page fuzzy-candidate walk — so structured sites cost a single request.
    raw_html = fetch_page(url, ssl_permissive)
    if raw_html:
        try:
            structured = (product_extract.from_structured_data(raw_html, url)
                          or product_extract.from_product_cards(raw_html, url, hints=hints))
        except Exception as e:
            structured = []
            if log:
                log.warning(f"[collection_fetch] product_extract failed for {url}: {e}")
        if structured:
            if log:
                log.info(f"[collection_fetch] structured extract — {len(structured)} products for {url}")
            return _strip_text(raw_html), structured, []

    # Unstructured: walk pagination for combined text + best-effort fuzzy candidates.
    try:
        paged, candidates = fetch_paginated_html(
            url, fetch_page, ssl_permissive=ssl_permissive, log=log)
        if paged:
            return paged, None, candidates
    except Exception as e:
        if log:
            log.warning(f"[collection_fetch] paginated path failed for {url}: {e}")

    if raw_html is None:
        return None, None, []
    return _strip_text(raw_html), None, _candidates_from_html(raw_html, url)


def fetch_collection_text(url, fetch_page, ssl_permissive=False, log=None):
    """Text-only convenience wrapper around fetch_collection (back-compat)."""
    text, _products, _candidates = fetch_collection(
        url, fetch_page, ssl_permissive=ssl_permissive, log=log)
    return text
