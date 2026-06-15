"""URL normalization for watch matching — single source of truth.

A user-watch drop is matched to a watcher by comparing normalized URLs: the scraper
(web_watcher) stamps the drop, the alerter (per_user_alerter) and dashboard
(watcher_signup) match it. If those impls disagree on a URL, the watch is polled but
its drops never match — a silent missed alert (the S43 failure mode). So normalization
MUST live in one place. dealer_scout also groups candidate domains with the same logic.

Keep this module dependency-free so any agent can import it cheaply.

NOTE: `watcher_signup.normalize_url` is a DIFFERENT function (strips tracking query
params + preserves case for storage) — not a matching normalizer; leave it alone.
"""
import re

_SCHEME_WWW = re.compile(r'^https?://(www\.)?')


def normalize_watch_url(url):
    """Normalize a URL for exact-match scoping: strip surrounding whitespace, scheme,
    leading www, and trailing slash; lowercase. Anchored to the prefix so an embedded
    'http://' inside the path is preserved."""
    return _SCHEME_WWW.sub('', (url or '').strip().lower()).rstrip('/')


def domain_from_url(url):
    """Bare domain: normalize then take the host, dropping any path, query, or
    fragment. A domain never contains '/', '?' or '#' — splitting on only '/'
    leaks a query string into the host for path-less URLs (e.g. a UTM-appended
    homepage link https://shop.com?utm_source=x), breaking domain equality."""
    host = _SCHEME_WWW.sub('', (url or '').strip().lower()).split('/')[0]
    return re.split(r'[?#]', host, 1)[0]
